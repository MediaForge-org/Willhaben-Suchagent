import asyncio
from collections.abc import Callable
from dataclasses import replace

import pytest

from agent.app.core.enrichment import ListingEnricher
from agent.app.core.exceptions import (
    AccessDeniedError,
    ChallengeDetectedError,
    ParseError,
    RateLimitedError,
    RequestTimeoutError,
)
from agent.app.core.health import HealthState
from agent.app.core.models import EnrichmentStatus, Listing, SellerType
from agent.app.core.scheduler import Scheduler
from agent.app.notifications.service import FakeNotificationService, NotificationService
from agent.app.storage.database import Database, SearchCreateData
from agent.app.willhaben.fake_provider import FakeListingProvider


class FlakyNotificationService(NotificationService):
    def __init__(self, *, failing: bool = True) -> None:
        self.failing = failing
        self.attempted: list[str] = []
        self.sent: list[str] = []

    async def notify_new_listing(self, listing: Listing) -> None:
        self.attempted.append(listing.provider_listing_id)
        if self.failing:
            raise RuntimeError("simulated ntfy outage")
        self.sent.append(listing.provider_listing_id)

    async def notify_test(self) -> None:
        if self.failing:
            raise RuntimeError("simulated ntfy outage")


class TrackingListingEnricher(ListingEnricher):
    def __init__(self, error: Exception | None = None, delay_seconds: float = 0) -> None:
        self.error = error
        self.delay_seconds = delay_seconds
        self.calls: list[str] = []
        self.active_requests = 0
        self.max_observed_concurrency = 0

    async def enrich(self, listing: Listing) -> Listing:
        self.calls.append(listing.provider_listing_id)
        self.active_requests += 1
        self.max_observed_concurrency = max(
            self.max_observed_concurrency,
            self.active_requests,
        )
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            if self.error is not None:
                raise self.error
            return listing.model_copy(
                update={
                    "seller_name": "Max M.",
                    "seller_type": SellerType.PRIVATE,
                    "condition": "Sehr gut",
                    "location": "Wien, 22. Bezirk",
                    "enrichment_status": EnrichmentStatus.ENRICHED,
                }
            )
        finally:
            self.active_requests -= 1


@pytest.mark.asyncio
async def test_baseline_creates_no_detail_requests(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(
        search.id,
        [listing_factory(f"baseline-{index}") for index in range(30)],
    )
    enricher = TrackingListingEnricher()

    await scheduler_factory(listing_enricher=enricher).run_cycle()

    assert enricher.calls == []
    assert await database.count("listings") == 30


@pytest.mark.asyncio
async def test_known_listing_creates_no_detail_request(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    known = listing_factory("known-detail")
    provider.set_results(search.id, [known])
    enricher = TrackingListingEnricher()
    scheduler = scheduler_factory(listing_enricher=enricher)

    await scheduler.run_cycle()
    await scheduler.run_cycle()

    assert enricher.calls == []


@pytest.mark.asyncio
async def test_exactly_one_new_listing_creates_one_detail_request(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    enricher = TrackingListingEnricher()
    scheduler = scheduler_factory(listing_enricher=enricher)
    await scheduler.run_cycle()

    provider.set_results(search.id, [listing_factory("one-new")])
    await scheduler.run_cycle()

    assert enricher.calls == ["one-new"]
    assert notifications.notifications[0].seller_name == "Max M."


@pytest.mark.asyncio
async def test_two_new_listings_create_one_controlled_detail_request_each(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    enricher = TrackingListingEnricher()
    scheduler = scheduler_factory(listing_enricher=enricher)
    await scheduler.run_cycle()

    provider.set_results(search.id, [listing_factory("new-a"), listing_factory("new-b")])
    await scheduler.run_cycle()

    assert sorted(enricher.calls) == ["new-a", "new-b"]


@pytest.mark.asyncio
async def test_detail_enrichment_uses_scheduler_concurrency_limit(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    enricher = TrackingListingEnricher(delay_seconds=0.01)
    scheduler = scheduler_factory(
        listing_enricher=enricher,
        max_concurrent_requests=2,
    )
    await scheduler.run_cycle()
    provider.set_results(
        search.id,
        [listing_factory(f"limited-{index}") for index in range(5)],
    )

    await scheduler.run_cycle()

    assert enricher.max_observed_concurrency == 2


@pytest.mark.asyncio
async def test_enriched_listing_is_not_loaded_again(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    enricher = TrackingListingEnricher()
    scheduler = scheduler_factory(listing_enricher=enricher)
    await scheduler.run_cycle()
    new = listing_factory("one-shot")
    provider.set_results(search.id, [new])

    await scheduler.run_cycle()
    await scheduler.run_cycle()

    assert enricher.calls == ["one-shot"]
    recent = await database.list_recent_listings(limit=1)
    assert recent[0].enrichment_status is EnrichmentStatus.ENRICHED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "detail_error",
    [
        RequestTimeoutError("simulated detail timeout"),
        ParseError("simulated detail parse failure"),
        AccessDeniedError("simulated detail 403"),
        RateLimitedError("simulated detail 429"),
        ChallengeDetectedError("simulated detail challenge"),
    ],
    ids=["timeout", "parse-error", "403", "429", "challenge"],
)
async def test_detail_failure_does_not_prevent_push(
    detail_error: Exception,
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    enricher = TrackingListingEnricher(detail_error)
    scheduler = scheduler_factory(listing_enricher=enricher)
    await scheduler.run_cycle()
    provider.set_results(search.id, [listing_factory("detail-fails")])

    await scheduler.run_cycle()

    assert enricher.calls == ["detail-fails"]
    assert [item.provider_listing_id for item in notifications.notifications] == ["detail-fails"]
    assert notifications.notifications[0].enrichment_status is EnrichmentStatus.FAILED


@pytest.mark.asyncio
async def test_failed_enrichment_is_not_retried_while_notification_is_pending(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    enricher = TrackingListingEnricher(RequestTimeoutError("simulated detail timeout"))
    disabled_notifications = FakeNotificationService()
    disabled_notifications.enabled = False
    disabled_notifications.disabled_reason = "test"
    scheduler = scheduler_factory(
        listing_enricher=enricher,
        notification_service=disabled_notifications,
    )
    await scheduler.run_cycle()
    listing = listing_factory("no-detail-retry")
    provider.set_results(search.id, [listing])

    await scheduler.run_cycle()
    await scheduler.run_cycle()

    assert enricher.calls == ["no-detail-retry"]
    recent = (await database.list_recent_listings(limit=1))[0]
    assert recent.enrichment_status is EnrichmentStatus.FAILED


@pytest.mark.asyncio
async def test_disabled_search_is_not_executed(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
) -> None:
    search_data.enabled = False
    search = await database.create_search(search_data)

    await scheduler_factory().run_cycle()

    assert search.id not in provider.calls


@pytest.mark.asyncio
async def test_baseline_then_one_notification_then_deduplication(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    existing = listing_factory("existing")
    provider.set_results(search.id, [existing])
    scheduler = scheduler_factory()

    await scheduler.run_cycle()
    assert notifications.notifications == []
    assert await database.count("listings") == 1
    assert await database.count("notifications") == 0
    initialized_search = await database.get_search(search.id)
    assert initialized_search is not None
    assert initialized_search.baseline_initialized is True

    new_listing = listing_factory("new")
    provider.set_results(search.id, [existing, new_listing])
    await scheduler.run_cycle()
    assert [item.provider_listing_id for item in notifications.notifications] == ["new"]
    assert await database.count("notifications") == 1

    await scheduler.run_cycle()
    assert len(notifications.notifications) == 1
    assert await database.count("notifications") == 1


@pytest.mark.asyncio
async def test_shared_listing_notifies_once_but_stores_both_matches(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    first = await database.create_search(search_data)
    second_data = replace(search_data, name="BMW 340i", query="BMW 340i")
    second = await database.create_search(second_data)
    scheduler = scheduler_factory()

    await scheduler.run_cycle()
    shared = listing_factory("shared")
    provider.set_results(first.id, [shared])
    provider.set_results(second.id, [shared])
    await scheduler.run_cycle()

    assert len(notifications.notifications) == 1
    assert await database.count("listings") == 1
    assert await database.count("search_matches") == 2
    assert await database.count("notifications") == 1


@pytest.mark.asyncio
async def test_known_listings_survive_database_restart(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    listing = listing_factory("persistent")
    provider.set_results(search.id, [listing])
    await scheduler_factory().run_cycle()

    restarted_database = Database(database.path)
    await restarted_database.initialize()
    restarted_provider = FakeListingProvider()
    restarted_notifications = FakeNotificationService()
    restarted_provider.set_results(search.id, [listing])
    restarted_scheduler = Scheduler(
        database=restarted_database,
        provider=restarted_provider,
        notification_service=restarted_notifications,
        health=HealthState(),
        cycle_interval_seconds=60,
        max_concurrent_requests=2,
    )
    await restarted_scheduler.run_cycle()

    assert await restarted_database.count("listings") == 1
    assert restarted_notifications.notifications == []


@pytest.mark.asyncio
async def test_all_searches_share_one_cycle_and_concurrency_is_limited(
    database: Database,
    search_data: SearchCreateData,
    scheduler_factory: Callable[..., Scheduler],
) -> None:
    searches = []
    for index in range(5):
        data = replace(search_data, name=f"Search {index}")
        searches.append(await database.create_search(data))
    slow_provider = FakeListingProvider(delay_seconds=0.02)
    health = HealthState()
    scheduler = scheduler_factory(
        provider=slow_provider,
        health=health,
        max_concurrent_requests=2,
    )

    await scheduler.run_cycle()

    assert set(slow_provider.calls) == {search.id for search in searches}
    assert health.total_cycle_count == 1
    assert slow_provider.max_observed_concurrency == 2


@pytest.mark.asyncio
async def test_scheduler_cadence_is_measured_from_previous_cycle_start(
    database: Database,
    search_data: SearchCreateData,
) -> None:
    search = await database.create_search(search_data)
    provider = FakeListingProvider(delay_seconds=0.02)
    provider.set_results(search.id, [])
    scheduler = Scheduler(
        database=database,
        provider=provider,
        notification_service=FakeNotificationService(),
        health=HealthState(),
        cycle_interval_seconds=0.08,
        max_concurrent_requests=1,
    )

    scheduler.start()
    try:
        async with asyncio.timeout(1):
            await provider.wait_for_call_count(3)
    finally:
        await scheduler.stop()

    intervals = [
        later - earlier
        for earlier, later in zip(
            provider.call_started_at[:2],
            provider.call_started_at[1:3],
            strict=True,
        )
    ]
    assert all(0.055 <= interval < 0.12 for interval in intervals)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_type",
    [RequestTimeoutError, RateLimitedError, AccessDeniedError, ChallengeDetectedError],
)
async def test_expected_provider_errors_do_not_destroy_scheduler(
    error_type: type[Exception],
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
) -> None:
    search = await database.create_search(search_data)
    provider.set_error(search.id, error_type("simulated"))
    health = HealthState()
    scheduler = scheduler_factory(health=health)

    await scheduler.run_cycle()
    assert provider.calls == [search.id]
    provider.set_results(search.id, [])
    await scheduler.run_cycle()

    refreshed = await database.get_search(search.id)
    assert health.total_cycle_count == 2
    assert health.failed_cycle_count == 0
    assert health.last_successful_cycle_at is not None
    assert refreshed is not None
    assert refreshed.consecutive_errors == 0
    assert refreshed.baseline_initialized is True


@pytest.mark.asyncio
async def test_notification_failure_is_persisted_and_retried_in_later_cycle(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    notifications = FlakyNotificationService()
    health = HealthState()
    scheduler = scheduler_factory(notification_service=notifications, health=health)
    await scheduler.run_cycle()

    new_listing = listing_factory("retry-me")
    provider.set_results(search.id, [new_listing])
    await scheduler.run_cycle()

    failed = await database.notification_status("retry-me")
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["attempt_count"] == 1
    assert "RuntimeError" in failed["last_error"]
    assert health.failed_cycle_count == 0
    assert notifications.attempted == ["retry-me"]

    notifications.failing = False
    await scheduler.run_cycle()

    sent = await database.notification_status("retry-me")
    assert sent is not None
    assert sent["status"] == "sent"
    assert sent["attempt_count"] == 2
    assert sent["last_error"] is None
    assert notifications.sent == ["retry-me"]
    assert health.last_successful_notification_at is not None


@pytest.mark.asyncio
async def test_disabled_notification_service_keeps_notification_pending(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    disabled = FlakyNotificationService(failing=False)
    disabled.enabled = False
    disabled.disabled_reason = "not configured"
    scheduler = scheduler_factory(notification_service=disabled)
    await scheduler.run_cycle()
    provider.set_results(search.id, [listing_factory("waiting-for-config")])

    await scheduler.run_cycle()

    notification = await database.notification_status("waiting-for-config")
    assert notification is not None
    assert notification["status"] == "pending"
    assert notification["attempt_count"] == 0
    assert disabled.attempted == []


@pytest.mark.asyncio
async def test_restart_retries_failed_notification_without_duplicate_listing(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    failing = FlakyNotificationService()
    scheduler = scheduler_factory(notification_service=failing)
    await scheduler.run_cycle()
    provider.set_results(search.id, [listing_factory("survives-restart")])
    await scheduler.run_cycle()

    restarted_database = Database(database.path)
    await restarted_database.initialize()
    restarted_provider = FakeListingProvider()
    restarted_provider.set_results(search.id, [])
    restarted_notifications = FakeNotificationService()
    restarted_scheduler = Scheduler(
        database=restarted_database,
        provider=restarted_provider,
        notification_service=restarted_notifications,
        health=HealthState(),
        cycle_interval_seconds=60,
        max_concurrent_requests=2,
    )
    await restarted_scheduler.run_cycle()

    assert [item.provider_listing_id for item in restarted_notifications.notifications] == [
        "survives-restart"
    ]
    assert await restarted_database.count("listings") == 1
    notification = await restarted_database.notification_status("survives-restart")
    assert notification is not None
    assert notification["status"] == "sent"


@pytest.mark.asyncio
async def test_sent_notification_is_not_repeated_after_restart(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    provider.set_results(search.id, [])
    await scheduler_factory().run_cycle()
    listing = listing_factory("already-sent")
    provider.set_results(search.id, [listing])
    await scheduler_factory().run_cycle()

    restarted_database = Database(database.path)
    await restarted_database.initialize()
    restarted_provider = FakeListingProvider()
    restarted_provider.set_results(search.id, [listing])
    restarted_notifications = FakeNotificationService()
    restarted_scheduler = Scheduler(
        database=restarted_database,
        provider=restarted_provider,
        notification_service=restarted_notifications,
        health=HealthState(),
        cycle_interval_seconds=60,
        max_concurrent_requests=2,
    )
    await restarted_scheduler.run_cycle()

    assert restarted_notifications.notifications == []
    notification = await restarted_database.notification_status("already-sent")
    assert notification is not None
    assert notification["status"] == "sent"
    assert notification["attempt_count"] == 1


@pytest.mark.asyncio
async def test_reactivated_initialized_search_only_notifies_unknown_listing(
    database: Database,
    search_data: SearchCreateData,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
    scheduler_factory: Callable[..., Scheduler],
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    known = listing_factory("known-before-disable")
    provider.set_results(search.id, [known])
    scheduler = scheduler_factory()
    await scheduler.run_cycle()
    await database.update_search(search.id, {"enabled": False})
    reactivated = await database.update_search(search.id, {"enabled": True})
    assert reactivated is not None
    assert reactivated.baseline_initialized is True

    unknown = listing_factory("new-after-reactivation")
    provider.set_results(search.id, [known, unknown])
    await scheduler.run_cycle()

    assert [item.provider_listing_id for item in notifications.notifications] == [
        "new-after-reactivation"
    ]
