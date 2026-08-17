from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from agent.app._version import __version__
from agent.app.api.schemas import (
    AgentSettingsPatch,
    AgentSettingsResponse,
    BackupImportSummaryResponse,
    ChannelTestResponse,
    DesktopSoundOption,
    DesktopSoundTestRequest,
    DesktopSoundTestResponse,
    GlobalNotificationSettingsPatch,
    GlobalNotificationSettingsResponse,
    HealthResponse,
    ImportedSearchDraftResponse,
    ImportSearchUrlRequest,
    MarketplaceOption,
    MarketplaceOptionsResponse,
    NotificationTargetCreate,
    NotificationTargetDeleteResponse,
    NotificationTargetPatch,
    NotificationTargetResponse,
    RecentListingResponse,
    SearchCreate,
    SearchPatch,
    SearchResponse,
    StatusResponse,
    TemplateCreate,
    TemplatePatch,
    TemplateRenderRequest,
    TemplateRenderResponse,
    TemplateResponse,
)
from agent.app.backup.service import (
    BackupValidationError,
    export_backup,
    import_backup,
    parse_backup_document,
)
from agent.app.core.templates import render_template, validate_template_body
from agent.app.notifications.service import (
    InvalidChannelConfigurationError,
    NotificationDeliveryError,
    NotificationDisabledError,
    NotificationService,
)
from agent.app.notifications.settings_manager import NotificationSettingsManager
from agent.app.notifications.sound import SOUND_VARIANTS, DesktopNotificationSoundService
from agent.app.notifications.targets import (
    NotificationTargetNotFoundError,
    NotificationTargetService,
    NotificationTargetSnapshot,
)
from agent.app.storage.database import Database, SearchCreateData, TemplateCreateData
from agent.app.willhaben.marketplace_search import (
    SUPPORTED_MARKETPLACE_CATEGORIES,
    SUPPORTED_MARKETPLACE_LOCATIONS,
)
from agent.app.willhaben.search_url_import import (
    InvalidSearchUrlError,
    parse_marketplace_search_url,
)

router = APIRouter()


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_notification_service(request: Request) -> NotificationService:
    return request.app.state.notification_service


def get_desktop_sound_service(request: Request) -> DesktopNotificationSoundService:
    return request.app.state.desktop_sound_service


def get_notification_settings_manager(request: Request) -> NotificationSettingsManager | None:
    return getattr(request.app.state, "notification_settings_manager", None)


def get_notification_target_service(request: Request) -> NotificationTargetService | None:
    return getattr(request.app.state, "notification_target_service", None)


_UNAVAILABLE_NOTIFICATIONS = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="Benachrichtigungseinstellungen sind in diesem Modus nicht verfügbar.",
)


async def _global_notifications_response(
    manager: NotificationSettingsManager,
) -> GlobalNotificationSettingsResponse:
    snapshot = await manager.snapshot()
    return GlobalNotificationSettingsResponse(
        ntfy_timeout_seconds=snapshot.ntfy_timeout_seconds,
        discord_timeout_seconds=snapshot.discord_timeout_seconds,
        email_smtp_host=snapshot.email_smtp_host,
        email_smtp_port=snapshot.email_smtp_port,
        email_smtp_username=snapshot.email_smtp_username,
        email_smtp_password_configured=snapshot.email_smtp_password_configured,
        email_from_address=snapshot.email_from_address,
        email_encryption=snapshot.email_encryption,  # type: ignore[arg-type]
        email_timeout_seconds=snapshot.email_timeout_seconds,
    )


def _target_response(
    snapshot: NotificationTargetSnapshot, *, usage_count: int = 0
) -> NotificationTargetResponse:
    return NotificationTargetResponse(
        id=snapshot.id,
        type=snapshot.type,  # type: ignore[arg-type]
        name=snapshot.name,
        enabled=snapshot.enabled,
        configured=snapshot.configured,
        ntfy_base_url=snapshot.ntfy_base_url,
        ntfy_topic_configured=snapshot.ntfy_topic_configured,
        ntfy_token_configured=snapshot.ntfy_token_configured,
        discord_webhook_configured=snapshot.discord_webhook_configured,
        email_address=snapshot.email_address,
        email_address_masked=snapshot.email_address_masked,
        usage_count=usage_count,
        created_at=snapshot.created_at,
        updated_at=snapshot.updated_at,
    )


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    database = get_database(request)
    state = request.app.state.health
    active_searches = len(await database.list_searches(enabled_only=True))
    return HealthResponse(
        status=state.status,
        process_started_at=state.process_started_at,
        last_cycle_started_at=state.last_cycle_started_at,
        next_cycle_due_at=state.next_cycle_due_at,
        last_cycle_completed_at=state.last_cycle_completed_at,
        last_successful_cycle_at=state.last_successful_cycle_at,
        last_successful_willhaben_cycle_at=state.last_successful_willhaben_cycle_at,
        active_searches=active_searches,
        total_cycle_count=state.total_cycle_count,
        failed_cycle_count=state.failed_cycle_count,
    )


@router.get("/api/v1/status", response_model=StatusResponse, tags=["health"])
async def application_status(request: Request) -> StatusResponse:
    base = await health(request)
    state = request.app.state.health
    settings = request.app.state.settings
    database = get_database(request)
    notifications = get_notification_service(request)
    desktop_sound = get_desktop_sound_service(request)
    persisted_last_notification = await database.last_successful_notification_at()
    last_notification = state.last_successful_notification_at
    if persisted_last_notification is not None and (
        last_notification is None or persisted_last_notification > last_notification
    ):
        last_notification = persisted_last_notification
    return StatusResponse(
        **base.model_dump(),
        app_version=__version__,
        environment=settings.app_environment,
        scheduler_running=state.scheduler_running,
        cycle_interval_seconds=settings.cycle_interval_seconds,
        max_concurrent_requests=settings.max_concurrent_requests,
        last_cycle_duration_seconds=state.last_cycle_duration_seconds,
        last_cycle_error=state.last_cycle_error,
        last_notification_error=state.last_notification_error,
        last_provider_errors=state.last_provider_errors,
        pending_notifications=await database.count_notifications_with_status("pending"),
        failed_notifications=await database.count_notifications_with_status("failed"),
        last_successful_notification_at=last_notification,
        notifications_enabled=notifications.enabled,
        notifications_disabled_reason=notifications.disabled_reason,
        desktop_sound_enabled=desktop_sound.enabled,
        desktop_sound_id=desktop_sound.sound_id,
        desktop_sound_available=desktop_sound.available,
        desktop_sound_disabled_reason=desktop_sound.disabled_reason,
        database_counts=await database.status_counts(),
    )


async def _settings_response(
    request: Request,
    *,
    enabled: bool,
    sound_id: str,
) -> AgentSettingsResponse:
    manager = get_notification_settings_manager(request)
    return AgentSettingsResponse(
        desktop_sound_enabled=enabled,
        desktop_sound_id=sound_id,
        desktop_sounds=[
            DesktopSoundOption(id=variant.id, name=variant.name)
            for variant in SOUND_VARIANTS.values()
        ],
        notifications=(await _global_notifications_response(manager)) if manager else None,
    )


@router.get("/api/v1/settings", response_model=AgentSettingsResponse, tags=["settings"])
async def agent_settings(request: Request) -> AgentSettingsResponse:
    preferences = await get_database(request).get_desktop_sound_preferences()
    return await _settings_response(
        request, enabled=preferences.enabled, sound_id=preferences.sound_id
    )


@router.patch("/api/v1/settings", response_model=AgentSettingsResponse, tags=["settings"])
async def update_agent_settings(
    payload: AgentSettingsPatch,
    request: Request,
) -> AgentSettingsResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes or any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Mindestens eine Einstellung ist erforderlich")
    try:
        preferences = await get_database(request).update_desktop_sound_preferences(
            enabled=changes.get("desktop_sound_enabled"),
            sound_id=changes.get("desktop_sound_id"),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    get_desktop_sound_service(request).configure(
        enabled=preferences.enabled,
        sound_id=preferences.sound_id,
    )
    return await _settings_response(
        request, enabled=preferences.enabled, sound_id=preferences.sound_id
    )


@router.patch(
    "/api/v1/settings/notifications",
    response_model=GlobalNotificationSettingsResponse,
    tags=["settings"],
)
async def update_notification_settings(
    payload: GlobalNotificationSettingsPatch,
    request: Request,
) -> GlobalNotificationSettingsResponse:
    manager = get_notification_settings_manager(request)
    if manager is None:
        raise _UNAVAILABLE_NOTIFICATIONS
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Mindestens eine Einstellung ist erforderlich")
    try:
        await manager.update_global(changes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await _global_notifications_response(manager)


# -- Notification targets (reusable ntfy/Discord/e-mail destinations) ------------------


@router.get(
    "/api/v1/notification-targets",
    response_model=list[NotificationTargetResponse],
    tags=["notifications"],
)
async def list_notification_targets(request: Request) -> list[NotificationTargetResponse]:
    service = get_notification_target_service(request)
    if service is None:
        raise _UNAVAILABLE_NOTIFICATIONS
    snapshots = await service.list()
    return [
        _target_response(snapshot, usage_count=await service.usage_count(snapshot.id))
        for snapshot in snapshots
    ]


@router.post(
    "/api/v1/notification-targets",
    response_model=NotificationTargetResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["notifications"],
)
async def create_notification_target(
    payload: NotificationTargetCreate, request: Request
) -> NotificationTargetResponse:
    service = get_notification_target_service(request)
    if service is None:
        raise _UNAVAILABLE_NOTIFICATIONS
    try:
        snapshot = await service.create(payload.model_dump(exclude_unset=True))
    except InvalidChannelConfigurationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _target_response(snapshot)


@router.patch(
    "/api/v1/notification-targets/{target_id}",
    response_model=NotificationTargetResponse,
    tags=["notifications"],
)
async def update_notification_target(
    target_id: int, payload: NotificationTargetPatch, request: Request
) -> NotificationTargetResponse:
    service = get_notification_target_service(request)
    if service is None:
        raise _UNAVAILABLE_NOTIFICATIONS
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Mindestens ein Feld ist erforderlich")
    try:
        snapshot = await service.update(target_id, changes)
    except NotificationTargetNotFoundError as error:
        raise HTTPException(status_code=404, detail="Notification target not found") from error
    except InvalidChannelConfigurationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _target_response(snapshot, usage_count=await service.usage_count(target_id))


@router.delete(
    "/api/v1/notification-targets/{target_id}",
    response_model=NotificationTargetDeleteResponse,
    tags=["notifications"],
)
async def delete_notification_target(
    target_id: int, request: Request
) -> NotificationTargetDeleteResponse:
    service = get_notification_target_service(request)
    if service is None:
        raise _UNAVAILABLE_NOTIFICATIONS
    try:
        usage_count = await service.delete(target_id)
    except NotificationTargetNotFoundError as error:
        raise HTTPException(status_code=404, detail="Notification target not found") from error
    return NotificationTargetDeleteResponse(deleted=True, searches_affected=usage_count)


@router.post(
    "/api/v1/notification-targets/{target_id}/test",
    response_model=ChannelTestResponse,
    tags=["notifications"],
)
async def test_notification_target(target_id: int, request: Request) -> ChannelTestResponse:
    service = get_notification_target_service(request)
    if service is None:
        raise _UNAVAILABLE_NOTIFICATIONS
    try:
        await service.get(target_id)
    except NotificationTargetNotFoundError as error:
        raise HTTPException(status_code=404, detail="Notification target not found") from error
    channel_service = request.app.state.notification_target_registry.get(target_id)
    if channel_service is None or not channel_service.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(channel_service.disabled_reason if channel_service else None)
            or "Dieses Ziel ist noch nicht eingerichtet.",
        )
    try:
        await channel_service.notify_test()
    except NotificationDisabledError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    except NotificationDeliveryError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error)) from error
    return ChannelTestResponse(status="sent", message="Willhaben-Suchagent – Test erfolgreich")


@router.get("/api/v1/searches", response_model=list[SearchResponse], tags=["searches"])
async def list_searches(request: Request) -> list[SearchResponse]:
    searches = await get_database(request).list_searches()
    return [SearchResponse.model_validate(item.model_dump()) for item in searches]


@router.post(
    "/api/v1/searches",
    response_model=SearchResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["searches"],
)
async def create_search(payload: SearchCreate, request: Request) -> SearchResponse:
    database = get_database(request)
    if payload.default_template_id is not None:
        if await database.get_template(payload.default_template_id) is None:
            raise HTTPException(status_code=422, detail="Standard-Template wurde nicht gefunden")
    await _validate_target_ids_or_422(database, payload.notification_target_ids)
    created = await database.create_search(SearchCreateData(**payload.model_dump()))
    return SearchResponse.model_validate(created.model_dump())


async def _validate_target_ids_or_422(database: Database, target_ids: list[int]) -> None:
    for target_id in target_ids:
        if await database.get_notification_target(target_id) is None:
            raise HTTPException(
                status_code=422,
                detail=f"Benachrichtigungsziel {target_id} wurde nicht gefunden",
            )


@router.get("/api/v1/searches/{search_id}", response_model=SearchResponse, tags=["searches"])
async def get_search(search_id: int, request: Request) -> SearchResponse:
    search = await get_database(request).get_search(search_id)
    if search is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return SearchResponse.model_validate(search.model_dump())


@router.patch("/api/v1/searches/{search_id}", response_model=SearchResponse, tags=["searches"])
async def update_search(
    search_id: int,
    payload: SearchPatch,
    request: Request,
) -> SearchResponse:
    changes = payload.model_dump(exclude_unset=True)
    required_fields = {
        "name",
        "category",
        "enabled",
        "query",
        "category_filters",
        "notify_desktop_sound",
    }
    if any(value is None for key, value in changes.items() if key in required_fields):
        raise HTTPException(status_code=422, detail="Field may not be null")
    database = get_database(request)
    template_id = changes.get("default_template_id")
    if template_id is not None and await database.get_template(template_id) is None:
        raise HTTPException(status_code=422, detail="Standard-Template wurde nicht gefunden")
    if "notification_target_ids" in changes and changes["notification_target_ids"] is not None:
        await _validate_target_ids_or_422(database, changes["notification_target_ids"])
    try:
        updated = await database.update_search(search_id, changes)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if updated is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return SearchResponse.model_validate(updated.model_dump())


@router.delete(
    "/api/v1/searches/{search_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["searches"],
)
async def delete_search(search_id: int, request: Request) -> Response:
    if not await get_database(request).delete_search(search_id):
        raise HTTPException(status_code=404, detail="Search not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/v1/listings/recent",
    response_model=list[RecentListingResponse],
    tags=["listings"],
)
async def recent_listings(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    search_id: int | None = Query(default=None, ge=1),
) -> list[RecentListingResponse]:
    listings = await get_database(request).list_recent_listings(
        limit=limit,
        search_id=search_id,
    )
    return [
        RecentListingResponse(
            listing_id=item.id,
            provider_listing_id=item.provider_listing_id,
            title=item.title,
            article_label=item.article_label,
            article_phrase=item.article_phrase,
            price=item.price,
            location=item.location,
            image_url=item.image_url,
            seller_name=item.seller_name,
            seller_type=item.seller_type,
            condition=item.condition,
            enrichment_status=item.enrichment_status,
            url=item.url,
            first_seen_at=item.first_seen_at,
            search_ids=item.search_ids,
            search_names=item.search_names,
        )
        for item in listings
    ]


@router.get(
    "/api/v1/marketplace/options",
    response_model=MarketplaceOptionsResponse,
    tags=["searches"],
)
async def marketplace_options() -> MarketplaceOptionsResponse:
    return MarketplaceOptionsResponse(
        categories=[
            MarketplaceOption(label=label, value=value)
            for label, value in SUPPORTED_MARKETPLACE_CATEGORIES
        ],
        locations=[
            MarketplaceOption(label=location, value=location)
            for location in SUPPORTED_MARKETPLACE_LOCATIONS
        ],
    )


@router.post(
    "/api/v1/marketplace/import-search-url",
    response_model=ImportedSearchDraftResponse,
    tags=["searches"],
)
async def import_marketplace_search_url(
    payload: ImportSearchUrlRequest,
) -> ImportedSearchDraftResponse:
    try:
        draft = parse_marketplace_search_url(payload.url)
    except InvalidSearchUrlError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return ImportedSearchDraftResponse(
        category_path=draft.category_path,
        category_label=draft.category_label,
        query=draft.query,
        location=draft.location,
        price_min=draft.price_min,
        price_max=draft.price_max,
        unsupported_filters=draft.unsupported_filters,
    )


@router.get("/api/v1/backup/export", tags=["backup"])
async def export_backup_route(request: Request) -> dict[str, object]:
    return await export_backup(get_database(request))


@router.post(
    "/api/v1/backup/import",
    response_model=BackupImportSummaryResponse,
    tags=["backup"],
)
async def import_backup_route(request: Request) -> BackupImportSummaryResponse:
    try:
        document = await request.json()
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail="Die Backup-Datei ist kein gültiges JSON."
        ) from error
    try:
        backup = parse_backup_document(document)
    except BackupValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    summary = await import_backup(get_database(request), backup)
    return BackupImportSummaryResponse(
        templates_created=summary.templates_created,
        templates_skipped=summary.templates_skipped,
        notification_targets_created=summary.notification_targets_created,
        notification_targets_skipped=summary.notification_targets_skipped,
        searches_created=summary.searches_created,
        searches_skipped=summary.searches_skipped,
    )


def _validate_body_or_422(body: str) -> None:
    try:
        validate_template_body(body)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/api/v1/templates", response_model=list[TemplateResponse], tags=["templates"])
async def list_templates(request: Request) -> list[TemplateResponse]:
    templates = await get_database(request).list_templates()
    return [TemplateResponse.model_validate(item.model_dump()) for item in templates]


@router.post(
    "/api/v1/templates",
    response_model=TemplateResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["templates"],
)
async def create_template(payload: TemplateCreate, request: Request) -> TemplateResponse:
    _validate_body_or_422(payload.body)
    template = await get_database(request).create_template(
        TemplateCreateData(name=payload.name, body=payload.body)
    )
    return TemplateResponse.model_validate(template.model_dump())


@router.get("/api/v1/templates/{template_id}", response_model=TemplateResponse, tags=["templates"])
async def get_template(template_id: int, request: Request) -> TemplateResponse:
    template = await get_database(request).get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateResponse.model_validate(template.model_dump())


@router.patch(
    "/api/v1/templates/{template_id}", response_model=TemplateResponse, tags=["templates"]
)
async def update_template(
    template_id: int, payload: TemplatePatch, request: Request
) -> TemplateResponse:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Mindestens ein Feld ist erforderlich")
    if any(value is None for value in changes.values()):
        raise HTTPException(status_code=422, detail="Feld darf nicht null sein")
    if "body" in changes:
        _validate_body_or_422(changes["body"])
    template = await get_database(request).update_template(template_id, changes)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return TemplateResponse.model_validate(template.model_dump())


@router.delete(
    "/api/v1/templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["templates"],
)
async def delete_template(template_id: int, request: Request) -> Response:
    if not await get_database(request).delete_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/api/v1/templates/{template_id}/render",
    response_model=TemplateRenderResponse,
    tags=["templates"],
)
async def render_message_template(
    template_id: int, payload: TemplateRenderRequest, request: Request
) -> TemplateRenderResponse:
    database = get_database(request)
    template = await database.get_template(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    listing = await database.get_listing(payload.listing_id)
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return TemplateRenderResponse(
        template_id=template.id,
        listing_id=payload.listing_id,
        rendered_text=render_template(template.body, listing),
    )


@router.post(
    "/api/v1/desktop-sound/test",
    response_model=DesktopSoundTestResponse,
    tags=["notifications"],
)
async def test_desktop_sound(
    request: Request,
    payload: DesktopSoundTestRequest | None = None,
) -> DesktopSoundTestResponse:
    sound = get_desktop_sound_service(request)
    sound_id = payload.desktop_sound_id if payload and payload.desktop_sound_id else sound.sound_id
    if sound_id not in SOUND_VARIANTS:
        raise HTTPException(status_code=422, detail=f"Unsupported desktop sound id: {sound_id}")
    try:
        played = await sound.preview(sound_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Desktop-Sound konnte nicht abgespielt werden",
        ) from error
    if not played:
        raise HTTPException(
            status_code=(
                status.HTTP_502_BAD_GATEWAY
                if sound.available
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Desktop-Sound konnte nicht abgespielt werden"
                if sound.available
                else "Kein unterstützter Audio-Player gefunden"
            ),
        )
    return DesktopSoundTestResponse(
        status="played",
        message=f"{SOUND_VARIANTS[sound_id].name} wurde abgespielt",
    )
