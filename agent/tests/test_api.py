import httpx
import pytest
from fastapi import FastAPI

from agent.app.core.config import Settings
from agent.app.core.models import EnrichmentStatus, SearchCategory, SellerType
from agent.app.main import create_app
from agent.app.notifications.dispatcher import NotificationDispatcher
from agent.app.notifications.service import FakeNotificationService
from agent.app.notifications.sound import FakeDesktopNotificationSoundService
from agent.app.willhaben.fake_provider import FakeListingProvider
from agent.app.willhaben.marketplace_listing_enricher import (
    WillhabenMarketplaceListingEnricher,
)
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
async def test_search_notification_target_ids_default_empty_and_reject_unknown_ids(
    api_client: httpx.AsyncClient,
) -> None:
    created_response = await api_client.post(
        "/api/v1/searches",
        json={"name": "Toggle", "category": "marketplace", "query": "ThinkPad"},
    )
    created = created_response.json()
    assert created["notification_target_ids"] == []
    assert created["notify_desktop_sound"] is True

    rejected = await api_client.patch(
        f"/api/v1/searches/{created['id']}",
        json={"notify_desktop_sound": None},
    )
    assert rejected.status_code == 422

    unknown_target = await api_client.patch(
        f"/api/v1/searches/{created['id']}",
        json={"notification_target_ids": [999999]},
    )
    assert unknown_target.status_code == 422


@pytest.mark.asyncio
async def test_status_reports_aggregate_notification_state(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.get("/api/v1/status")
    body = response.json()
    assert response.status_code == 200
    assert "notifications_enabled" in body
    assert "notifications_disabled_reason" in body


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
    assert body["desktop_sound_enabled"] is False
    assert body["desktop_sound_id"] == "notify"
    assert body["desktop_sound_available"] is False
    assert body["desktop_sound_disabled_reason"] == "Desktop sound is disabled"
    assert body["database_counts"] == {
        "searches": 0,
        "listings": 0,
        "search_matches": 0,
        "notifications": 0,
    }


@pytest.mark.asyncio
async def test_status_and_recent_listing_reads_do_not_call_provider(
    api_client: httpx.AsyncClient,
    provider: FakeListingProvider,
) -> None:
    await api_client.get("/api/v1/status")
    await api_client.get("/api/v1/status")
    await api_client.get("/api/v1/listings/recent", params={"limit": 1})

    assert provider.calls == []


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
        image_url="https://cache.willhaben.at/test/recent-second.jpg",
        seller_name="Max M.",
        seller_type=SellerType.PRIVATE,
        condition="Sehr gut",
        location="Wien, 22. Bezirk",
        enrichment_status=EnrichmentStatus.ENRICHED,
    )
    provider.set_results(first_id, [shared])
    provider.set_results(second_id, [shared, only_second])
    await test_app.state.scheduler.run_cycle()

    response = await api_client.get("/api/v1/listings/recent", params={"limit": 1})
    assert response.status_code == 200
    assert len(response.json()) == 1
    item = response.json()[0]
    assert item["provider_listing_id"] == "recent-second"
    assert item["seller_name"] == "Max M."
    assert item["seller_type"] == "private"
    assert item["condition"] == "Sehr gut"
    assert item["location"] == "Wien, 22. Bezirk"
    assert item["image_url"] == "https://cache.willhaben.at/test/recent-second.jpg"
    assert item["enrichment_status"] == "enriched"

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


@pytest.mark.asyncio
async def test_default_application_uses_real_provider_and_no_targets_configured(
    settings: Settings,
) -> None:
    app = create_app(settings)
    assert isinstance(app.state.provider, WillhabenMarketplaceProvider)
    assert app.state.scheduler.provider is app.state.provider
    assert isinstance(app.state.scheduler.listing_enricher, WillhabenMarketplaceListingEnricher)
    assert isinstance(app.state.notification_service, NotificationDispatcher)
    assert app.state.notification_service.enabled is False

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            status_response = await client.get("/api/v1/status")

    assert status_response.json()["notifications_enabled"] is False


@pytest.mark.asyncio
async def test_development_desktop_sound_endpoint_plays_without_listing(
    settings: Settings,
) -> None:
    sound = FakeDesktopNotificationSoundService()
    app = create_app(
        settings.model_copy(update={"app_environment": "development"}),
        FakeListingProvider(),
        FakeNotificationService(),
        sound,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/v1/desktop-sound/test")

    assert response.status_code == 200
    assert response.json() == {"status": "played", "message": "Notify wurde abgespielt"}
    assert sound.preview_count == 1
    assert await app.state.database.count("listings") == 0


@pytest.mark.asyncio
async def test_desktop_sound_test_previews_selected_sound_even_when_notifications_are_off(
    settings: Settings,
) -> None:
    sound = FakeDesktopNotificationSoundService(enabled=False)
    app = create_app(
        settings.model_copy(update={"app_environment": "development"}),
        FakeListingProvider(),
        FakeNotificationService(),
        sound,
    )

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/desktop-sound/test",
                json={"desktop_sound_id": "pop"},
            )

    assert response.status_code == 200
    assert sound.play_count == 0
    assert sound.previewed_sound_ids == ["pop"]


@pytest.mark.asyncio
async def test_desktop_sound_settings_are_mutable_and_reject_invalid_ids(
    settings: Settings,
) -> None:
    sound = FakeDesktopNotificationSoundService(enabled=False)
    app = create_app(settings, FakeListingProvider(), FakeNotificationService(), sound)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            initial = await client.get("/api/v1/settings")
            changed = await client.patch(
                "/api/v1/settings",
                json={"desktop_sound_enabled": True, "desktop_sound_id": "ping"},
            )
            rejected = await client.patch(
                "/api/v1/settings",
                json={"desktop_sound_id": "signal"},
            )
            persisted = await client.get("/api/v1/settings")

    assert initial.json()["desktop_sound_enabled"] is False
    assert [item["id"] for item in initial.json()["desktop_sounds"]] == [
        "notify",
        "ping",
        "pop",
    ]
    assert changed.status_code == 200
    assert changed.json()["desktop_sound_enabled"] is True
    assert changed.json()["desktop_sound_id"] == "ping"
    assert sound.enabled is True
    assert sound.sound_id == "ping"
    assert rejected.status_code == 422
    assert persisted.json()["desktop_sound_id"] == "ping"


@pytest.mark.asyncio
async def test_desktop_sound_settings_survive_agent_restart(settings: Settings) -> None:
    first_sound = FakeDesktopNotificationSoundService(enabled=False)
    first = create_app(settings, FakeListingProvider(), FakeNotificationService(), first_sound)
    async with first.router.lifespan_context(first):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=first),
            base_url="http://test",
        ) as client:
            response = await client.patch(
                "/api/v1/settings",
                json={"desktop_sound_enabled": True, "desktop_sound_id": "pop"},
            )
            assert response.status_code == 200

    restarted_sound = FakeDesktopNotificationSoundService(enabled=False)
    restarted = create_app(
        settings,
        FakeListingProvider(),
        FakeNotificationService(),
        restarted_sound,
    )
    async with restarted.router.lifespan_context(restarted):
        preferences = await restarted.state.database.get_desktop_sound_preferences()

    assert preferences.enabled is True
    assert preferences.sound_id == "pop"
    assert restarted_sound.enabled is True
    assert restarted_sound.sound_id == "pop"


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


IPHONE_URL = (
    "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/apple/"
    "iphone-13-mini-5009987?keyword=iphone+13+mini&sfId=d16702ad-e779-4fc3-b3b5-"
    "4442c66247a9&rows=30&isNavigation=true"
)


@pytest.mark.asyncio
async def test_import_search_url_extracts_deep_category_and_drops_navigation_params(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.post(
        "/api/v1/marketplace/import-search-url", json={"url": IPHONE_URL}
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "category_path": "apple/iphone-13-mini-5009987",
        "category_label": "Apple → iPhone 13 Mini",
        "query": "iphone 13 mini",
        "location": None,
        "price_min": None,
        "price_max": None,
        "unsupported_filters": [],
    }


@pytest.mark.asyncio
async def test_import_search_url_rejects_unsafe_urls(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/marketplace/import-search-url",
        json={"url": "https://example.com/iad/kaufen-und-verkaufen/marktplatz"},
    )

    assert response.status_code == 422
    assert "example.com" not in response.text


@pytest.mark.asyncio
async def test_import_search_url_rejects_javascript_scheme(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/marketplace/import-search-url", json={"url": "javascript:alert(1)"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_created_search_can_use_deep_imported_category_without_keyword(
    api_client: httpx.AsyncClient,
) -> None:
    imported = await api_client.post(
        "/api/v1/marketplace/import-search-url", json={"url": IPHONE_URL}
    )
    draft = imported.json()

    created = await api_client.post(
        "/api/v1/searches",
        json={
            "name": "iPhone 13 Mini",
            "category": "marketplace",
            "query": "",
            "category_filters": {
                "marketplace_category": draft["category_path"],
                "marketplace_category_label": draft["category_label"],
            },
        },
    )

    assert created.status_code == 201
    body = created.json()
    assert body["query"] == ""
    assert body["category_filters"]["marketplace_category"] == "apple/iphone-13-mini-5009987"


@pytest.mark.asyncio
async def test_backup_export_contains_no_secrets(api_client: httpx.AsyncClient) -> None:
    await api_client.post(
        "/api/v1/searches",
        json={"name": "Notebook", "category": "marketplace", "query": "ThinkPad"},
    )

    export = await api_client.get("/api/v1/backup/export")
    assert export.status_code == 200
    document = export.json()
    assert document["format_version"] == 1
    assert "webhook" not in str(document).lower()

    imported = await api_client.post("/api/v1/backup/import", json=document)
    assert imported.status_code == 200
    body = imported.json()
    # Search already exists (same database) -> skipped, not duplicated.
    assert body["searches_created"] == 0
    assert body["searches_skipped"] == 1


@pytest.mark.asyncio
async def test_backup_import_rejects_broken_json(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/backup/import",
        content=b"{not valid json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_backup_import_rejects_unsupported_format_version(
    api_client: httpx.AsyncClient,
) -> None:
    response = await api_client.post(
        "/api/v1/backup/import", json={"format_version": 999, "searches": []}
    )
    assert response.status_code == 422
