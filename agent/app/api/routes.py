from fastapi import APIRouter, HTTPException, Query, Request, Response, status

from agent.app.api.schemas import (
    HealthResponse,
    NotificationTestResponse,
    RecentListingResponse,
    SearchCreate,
    SearchPatch,
    SearchResponse,
    StatusResponse,
)
from agent.app.core.time import utc_now
from agent.app.notifications.service import (
    NotificationDeliveryError,
    NotificationDisabledError,
    NotificationService,
)
from agent.app.storage.database import Database, SearchCreateData

router = APIRouter()


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_notification_service(request: Request) -> NotificationService:
    return request.app.state.notification_service


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    database = get_database(request)
    state = request.app.state.health
    active_searches = len(await database.list_searches(enabled_only=True))
    return HealthResponse(
        status=state.status,
        process_started_at=state.process_started_at,
        last_cycle_started_at=state.last_cycle_started_at,
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
        database_counts=await database.status_counts(),
    )


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
    created = await get_database(request).create_search(SearchCreateData(**payload.model_dump()))
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
    try:
        updated = await get_database(request).update_search(search_id, changes)
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
