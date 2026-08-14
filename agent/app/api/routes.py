from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from agent.app.api.schemas import (
    AgentSettingsPatch,
    AgentSettingsResponse,
    DesktopSoundOption,
    DesktopSoundTestRequest,
    DesktopSoundTestResponse,
    HealthResponse,
    MarketplaceOption,
    MarketplaceOptionsResponse,
    NotificationTestResponse,
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
from agent.app.core.templates import render_template, validate_template_body
from agent.app.core.time import utc_now
from agent.app.notifications.service import (
    NotificationDeliveryError,
    NotificationDisabledError,
    NotificationService,
)
from agent.app.notifications.sound import SOUND_VARIANTS, DesktopNotificationSoundService
from agent.app.storage.database import Database, SearchCreateData, TemplateCreateData
from agent.app.willhaben.marketplace_search import (
    SUPPORTED_MARKETPLACE_CATEGORIES,
    SUPPORTED_MARKETPLACE_LOCATIONS,
)

router = APIRouter()


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_notification_service(request: Request) -> NotificationService:
    return request.app.state.notification_service


def get_desktop_sound_service(request: Request) -> DesktopNotificationSoundService:
    return request.app.state.desktop_sound_service


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
        ntfy_enabled=notifications.enabled,
        ntfy_disabled_reason=notifications.disabled_reason,
        desktop_sound_enabled=desktop_sound.enabled,
        desktop_sound_id=desktop_sound.sound_id,
        desktop_sound_available=desktop_sound.available,
        desktop_sound_disabled_reason=desktop_sound.disabled_reason,
        database_counts=await database.status_counts(),
    )


def _settings_response(
    *,
    enabled: bool,
    sound_id: str,
) -> AgentSettingsResponse:
    return AgentSettingsResponse(
        desktop_sound_enabled=enabled,
        desktop_sound_id=sound_id,
        desktop_sounds=[
            DesktopSoundOption(id=variant.id, name=variant.name)
            for variant in SOUND_VARIANTS.values()
        ],
    )


@router.get("/api/v1/settings", response_model=AgentSettingsResponse, tags=["settings"])
async def agent_settings(request: Request) -> AgentSettingsResponse:
    preferences = await get_database(request).get_desktop_sound_preferences()
    return _settings_response(enabled=preferences.enabled, sound_id=preferences.sound_id)


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
    return _settings_response(enabled=preferences.enabled, sound_id=preferences.sound_id)


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
    created = await database.create_search(SearchCreateData(**payload.model_dump()))
    return SearchResponse.model_validate(created.model_dump())


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
    required_fields = {"name", "category", "enabled", "query", "category_filters"}
    if any(value is None for key, value in changes.items() if key in required_fields):
        raise HTTPException(status_code=422, detail="Field may not be null")
    database = get_database(request)
    template_id = changes.get("default_template_id")
    if template_id is not None and await database.get_template(template_id) is None:
        raise HTTPException(status_code=422, detail="Standard-Template wurde nicht gefunden")
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
    "/api/v1/notifications/test",
    response_model=NotificationTestResponse,
    tags=["notifications"],
)
async def test_notification(request: Request) -> NotificationTestResponse:
    notifications = get_notification_service(request)
    if not notifications.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=notifications.disabled_reason or "ntfy is disabled",
        )
    try:
        await notifications.notify_test()
    except NotificationDisabledError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    except NotificationDeliveryError as error:
        request.app.state.health.last_notification_error = type(error).__name__
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="ntfy test notification failed",
        ) from error
    except Exception as error:
        request.app.state.health.last_notification_error = type(error).__name__
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Notification test failed",
        ) from error
    request.app.state.health.last_notification_error = None
    request.app.state.health.last_successful_notification_at = utc_now()
    return NotificationTestResponse(
        status="sent",
        message="Willhaben-Suchagent – Test erfolgreich",
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
