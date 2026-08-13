import httpx
import pytest
from fastapi import FastAPI

from agent.app.core.config import Settings
from agent.app.core.models import SearchCategory
from agent.app.main import create_app
from agent.app.notifications.service import FakeNotificationService, NtfyNotificationService
from agent.app.willhaben.fake_provider import FakeListingProvider
from agent.app.willhaben.marketplace_provider import WillhabenMarketplaceProvider


@pytest.mark.asyncio
async def test_empty_database_and_health_start_correctly(api_client: httpx.AsyncClient) -> None:
    searches = await api_client.get("/api/v1/searches")
    health = await api_client.get("/health")

    assert searches.status_code == 200
    assert searches.json() == []
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["active_searches"] == 0
    assert health.json()["total_cycle_count"] == 0


@pytest.mark.asyncio
async def test_search_crud_lifecycle(api_client: httpx.AsyncClient) -> None:
    payload = {
        "name": "Notebook",
        "category": "marketplace",
        "query": "ThinkPad",
        "location": "Graz",
        "price_min": "100",
        "price_max": "1200",
        "category_filters": {"condition": "used"},
    }
    created_response = await api_client.post("/api/v1/searches", json=payload)
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["baseline_initialized"] is False

    fetched = await api_client.get(f"/api/v1/searches/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["query"] == "ThinkPad"

    updated = await api_client.patch(
        f"/api/v1/searches/{created['id']}",
        json={"name": "Business Notebook", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Business Notebook"
    assert updated.json()["enabled"] is False

    listed = await api_client.get("/api/v1/searches")
    assert len(listed.json()) == 1

    deleted = await api_client.delete(f"/api/v1/searches/{created['id']}")
    assert deleted.status_code == 204
    assert (await api_client.get(f"/api/v1/searches/{created['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_search_validation_and_missing_resources(api_client: httpx.AsyncClient) -> None:
    invalid = await api_client.post(
        "/api/v1/searches",
        json={
            "name": "Invalid",
            "category": "marketplace",
            "price_min": 200,
            "price_max": 100,
        },
    )
    assert invalid.status_code == 422
    missing_patch = await api_client.patch(
        "/api/v1/searches/999",
        json={"enabled": False},
    )
    assert missing_patch.status_code == 404
    assert (await api_client.delete("/api/v1/searches/999")).status_code == 404


@pytest.mark.asyncio
async def test_detailed_status_endpoint(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "test"
    assert body["scheduler_running"] is False
    assert body["cycle_interval_seconds"] == 60
    assert body["max_concurrent_requests"] == 2
    assert body["pending_notifications"] == 0
    assert body["failed_notifications"] == 0
    assert body["last_successful_notification_at"] is None
    assert body["ntfy_enabled"] is True
    assert body["database_counts"] == {
        "searches": 0,
        "listings": 0,
        "search_matches": 0,
        "notifications": 0,
    }


@pytest.mark.asyncio
async def test_notification_test_endpoint_sends_without_creating_listing(
    api_client: httpx.AsyncClient,
    notifications: FakeNotificationService,
) -> None:
    response = await api_client.post("/api/v1/notifications/test")

    assert response.status_code == 200
    assert response.json() == {
        "status": "sent",
        "message": "Willhaben-Suchagent – Test erfolgreich",
    }
    assert notifications.test_notification_count == 1
    status_response = await api_client.get("/api/v1/status")
    assert status_response.json()["database_counts"]["listings"] == 0
    assert status_response.json()["database_counts"]["notifications"] == 0


@pytest.mark.asyncio
async def test_recent_listings_endpoint_supports_limit_and_search_filter(
    api_client: httpx.AsyncClient,
    test_app: FastAPI,
    provider: FakeListingProvider,
    listing_factory,
) -> None:
    first_search_response = await api_client.post(
        "/api/v1/searches",
        json={
            "name": "ThinkPad",
            "category": "marketplace",
            "query": "ThinkPad",
            "category_filters": {"marketplace_category": "computer-software-5824"},
        },
    )
    second_search_response = await api_client.post(
        "/api/v1/searches",
        json={
            "name": "Notebook",
            "category": "marketplace",
            "query": "Notebook",
        },
    )
    first_id = first_search_response.json()["id"]
    second_id = second_search_response.json()["id"]
    await test_app.state.scheduler.run_cycle()

    shared = listing_factory(
        "recent-shared",
        category=SearchCategory.MARKETPLACE,
        title="ThinkPad X1",
        url="https://www.willhaben.at/iad/object/recent-shared",
    )
    only_second = listing_factory(
        "recent-second",
        category=SearchCategory.MARKETPLACE,
        title="Notebook",
        url="https://www.willhaben.at/iad/object/recent-second",
    )
    provider.set_results(first_id, [shared])
    provider.set_results(second_id, [shared, only_second])
    await test_app.state.scheduler.run_cycle()

    response = await api_client.get("/api/v1/listings/recent", params={"limit": 1})
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["provider_listing_id"] == "recent-second"

    filtered = await api_client.get(
        "/api/v1/listings/recent",
        params={"search_id": first_id},
    )
    assert filtered.status_code == 200
    assert [item["provider_listing_id"] for item in filtered.json()] == ["recent-shared"]
    assert filtered.json()[0]["search_ids"] == [first_id, second_id]
    assert filtered.json()[0]["search_names"] == ["ThinkPad", "Notebook"]
    assert filtered.json()[0]["listing_id"] > 0
    assert filtered.json()[0]["first_seen_at"] is not None


@pytest.mark.asyncio
async def test_status_reports_cycle_notification_and_ntfy_state(
    api_client: httpx.AsyncClient,
    test_app: FastAPI,
    provider: FakeListingProvider,
    listing_factory,
) -> None:
    created = await api_client.post(
        "/api/v1/searches",
        json={"name": "Monitor", "category": "marketplace", "query": "Monitor"},
    )
    search_id = created.json()["id"]
    await test_app.state.scheduler.run_cycle()
    provider.set_results(
        search_id,
        [listing_factory("status-new", category=SearchCategory.MARKETPLACE)],
    )
    await test_app.state.scheduler.run_cycle()

    body = (await api_client.get("/api/v1/status")).json()
    assert body["last_cycle_started_at"] is not None
    assert body["last_cycle_completed_at"] is not None
    assert body["last_successful_willhaben_cycle_at"] is not None
    assert body["active_searches"] == 1
    assert body["pending_notifications"] == 0
    assert body["last_successful_notification_at"] is not None
    assert body["ntfy_enabled"] is True


@pytest.mark.asyncio
async def test_default_application_uses_real_provider_and_disabled_ntfy(
    settings: Settings,
) -> None:
    app = create_app(settings)
    assert isinstance(app.state.provider, WillhabenMarketplaceProvider)
    assert app.state.scheduler.provider is app.state.provider
    assert isinstance(app.state.notification_service, NtfyNotificationService)
    assert app.state.notification_service.enabled is False

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/notifications/test")
            status_response = await client.get("/api/v1/status")

    assert response.status_code == 503
    assert status_response.json()["ntfy_enabled"] is False
    assert status_response.json()["ntfy_disabled_reason"] == "NTFY_ENABLED is false"


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_single_scheduler(settings: Settings) -> None:
    enabled_settings = settings.model_copy(update={"scheduler_enabled": True})
    app = create_app(
        enabled_settings,
        FakeListingProvider(),
        FakeNotificationService(),
    )

    assert app.state.health.scheduler_running is False
    async with app.router.lifespan_context(app):
        assert app.state.health.scheduler_running is True
        assert app.state.scheduler._task is not None
        assert app.state.scheduler._task.get_name() == "global-search-scheduler"
    assert app.state.health.scheduler_running is False
    assert app.state.scheduler._task is None
