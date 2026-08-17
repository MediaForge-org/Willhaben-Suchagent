from collections.abc import Callable
from dataclasses import replace

import pytest

from agent.app.core.models import Listing
from agent.app.notifications.dispatcher import NotificationDispatcher
from agent.app.notifications.service import NotificationDeliveryError, NotificationService
from agent.app.storage.database import Database, SearchCreateData


class RecordingChannel(NotificationService):
    def __init__(self, *, enabled: bool = True, failing: bool = False) -> None:
        self.enabled = enabled
        self.disabled_reason = None if enabled else "disabled for test"
        self.failing = failing
        self.sent: list[str] = []
        self.attempts = 0

    async def notify_new_listing(self, listing: Listing) -> None:
        self.attempts += 1
        if self.failing:
            raise RuntimeError("simulated channel outage")
        self.sent.append(listing.provider_listing_id)

    async def notify_test(self) -> None:
        self.attempts += 1
        if self.failing:
            raise RuntimeError("simulated channel outage")


class FakeTargetRegistry:
    """A minimal stand-in for NotificationTargetRegistry, wired directly to
    hand-picked RecordingChannel instances by target id."""

    def __init__(self, services: dict[int, NotificationService]) -> None:
        self._services = services

    def get(self, target_id: int) -> NotificationService | None:
        return self._services.get(target_id)

    def all_services(self) -> list[NotificationService]:
        return list(self._services.values())

    async def close(self) -> None:
        return None


async def _make_target(database: Database, name: str, *, enabled: bool = True) -> int:
    target = await database.create_notification_target(type="ntfy", name=name, enabled=enabled)
    return target.id


async def _create_dispatchable_listing(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
    provider_listing_id: str,
    **search_overrides: object,
) -> Listing:
    """Persist one search, initialize its baseline, then add exactly one new listing."""

    search = await database.create_search(replace(search_data, **search_overrides))
    await database.persist_cycle_results([(search, [])])
    initialized = await database.get_search(search.id)
    assert initialized is not None
    listing = listing_factory(provider_listing_id)
    await database.persist_cycle_results([(initialized, [listing])])
    return listing


async def _create_listing_matched_by_searches(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
    provider_listing_id: str,
    search_overrides: list[dict[str, object]],
) -> Listing:
    """Persist several searches, initialize their baselines, then have all of them
    match the same new listing in one cycle -- the multi-search-match scenario."""

    searches = [
        await database.create_search(replace(search_data, name=f"search-{index}", **overrides))
        for index, overrides in enumerate(search_overrides)
    ]
    await database.persist_cycle_results([(search, []) for search in searches])
    initialized = []
    for search in searches:
        refreshed = await database.get_search(search.id)
        assert refreshed is not None
        initialized.append(refreshed)
    listing = listing_factory(provider_listing_id)
    await database.persist_cycle_results([(search, [listing]) for search in initialized])
    return listing


@pytest.mark.asyncio
async def test_two_searches_with_different_targets_union_to_one_delivery_each(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    """Search A wants ntfy target only, Search B wants Discord+E-Mail targets only;
    both match one listing."""

    ntfy_id = await _make_target(database, "ntfy target")
    discord_id = await _make_target(database, "discord target")
    email_id = await _make_target(database, "email target")
    ntfy, discord, email = RecordingChannel(), RecordingChannel(), RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        targets=FakeTargetRegistry({ntfy_id: ntfy, discord_id: discord, email_id: email}),
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "cross-search-union",
        [
            {"notification_target_ids": [ntfy_id]},
            {"notification_target_ids": [discord_id, email_id]},
        ],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.attempts == 1
    assert discord.attempts == 1
    assert email.attempts == 1
    assert ntfy.sent == ["cross-search-union"]
    assert discord.sent == ["cross-search-union"]
    assert email.sent == ["cross-search-union"]


@pytest.mark.asyncio
async def test_same_target_referenced_by_both_matching_searches_delivers_exactly_once(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "shared ntfy target")
    ntfy = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, targets=FakeTargetRegistry({ntfy_id: ntfy})
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "both-want-ntfy",
        [
            {"notification_target_ids": [ntfy_id]},
            {"notification_target_ids": [ntfy_id]},
        ],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.attempts == 1
    assert ntfy.sent == ["both-want-ntfy"]


@pytest.mark.asyncio
async def test_two_separate_discord_targets_both_send_independently(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    """Two distinct Discord targets (e.g. two different webhooks) referenced by two
    different searches must both be delivered to -- they are not deduplicated with
    each other, only a *shared* target id is."""

    target_a = await _make_target(database, "Papa - Willhaben")
    target_b = await _make_target(database, "Maxim - Technik")
    channel_a, channel_b = RecordingChannel(), RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, targets=FakeTargetRegistry({target_a: channel_a, target_b: channel_b})
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "two-discord-targets",
        [
            {"notification_target_ids": [target_a]},
            {"notification_target_ids": [target_b]},
        ],
    )

    await dispatcher.notify_new_listing(listing)

    assert channel_a.sent == ["two-discord-targets"]
    assert channel_b.sent == ["two-discord-targets"]


@pytest.mark.asyncio
async def test_two_separate_email_targets_both_send_independently(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    target_papa = await _make_target(database, "Papa")
    target_maxim = await _make_target(database, "Maxim")
    channel_papa, channel_maxim = RecordingChannel(), RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        targets=FakeTargetRegistry({target_papa: channel_papa, target_maxim: channel_maxim}),
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "two-email-targets",
        [
            {"notification_target_ids": [target_papa]},
            {"notification_target_ids": [target_maxim]},
        ],
    )

    await dispatcher.notify_new_listing(listing)

    assert channel_papa.sent == ["two-email-targets"]
    assert channel_maxim.sent == ["two-email-targets"]


@pytest.mark.asyncio
async def test_target_referenced_by_no_search_is_skipped_not_delivered(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "unused target")
    ntfy = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, targets=FakeTargetRegistry({ntfy_id: ntfy})
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "no-target-referenced",
        [{"notification_target_ids": []}, {"notification_target_ids": []}],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.attempts == 0


@pytest.mark.asyncio
async def test_one_target_failure_across_a_shared_listing_does_not_block_others(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    discord_id = await _make_target(database, "discord")
    email_id = await _make_target(database, "email")
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    email = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        targets=FakeTargetRegistry({ntfy_id: ntfy, discord_id: discord, email_id: email}),
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "shared-partial-outage",
        [
            {"notification_target_ids": [ntfy_id, discord_id]},
            {"notification_target_ids": [discord_id, email_id]},
        ],
    )

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["shared-partial-outage"]
    assert email.sent == ["shared-partial-outage"]
    assert discord.attempts == 1
    assert discord.sent == []


@pytest.mark.asyncio
async def test_retry_after_shared_listing_failure_only_repeats_the_failed_target(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    discord_id = await _make_target(database, "discord")
    email_id = await _make_target(database, "email")
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    email = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        targets=FakeTargetRegistry({ntfy_id: ntfy, discord_id: discord, email_id: email}),
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "shared-retry",
        [
            {"notification_target_ids": [ntfy_id, discord_id]},
            {"notification_target_ids": [discord_id, email_id]},
        ],
    )

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_new_listing(listing)
    assert ntfy.attempts == 1
    assert email.attempts == 1
    assert discord.attempts == 1

    discord.failing = False
    await dispatcher.notify_new_listing(listing)

    assert ntfy.attempts == 1
    assert email.attempts == 1
    assert discord.attempts == 2
    assert discord.sent == ["shared-retry"]


@pytest.mark.asyncio
async def test_dispatcher_delivers_to_all_referenced_targets(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    discord_id = await _make_target(database, "discord")
    email_id = await _make_target(database, "email")
    ntfy, discord, email = RecordingChannel(), RecordingChannel(), RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        targets=FakeTargetRegistry({ntfy_id: ntfy, discord_id: discord, email_id: email}),
    )
    listing = await _create_dispatchable_listing(
        database,
        search_data,
        listing_factory,
        "multi-target",
        notification_target_ids=[ntfy_id, discord_id, email_id],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["multi-target"]
    assert discord.sent == ["multi-target"]
    assert email.sent == ["multi-target"]


@pytest.mark.asyncio
async def test_target_outage_does_not_block_other_targets(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    discord_id = await _make_target(database, "discord")
    email_id = await _make_target(database, "email")
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    email = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        targets=FakeTargetRegistry({ntfy_id: ntfy, discord_id: discord, email_id: email}),
    )
    listing = await _create_dispatchable_listing(
        database,
        search_data,
        listing_factory,
        "partial-outage",
        notification_target_ids=[ntfy_id, discord_id, email_id],
    )

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["partial-outage"]
    assert email.sent == ["partial-outage"]
    assert discord.attempts == 1


@pytest.mark.asyncio
async def test_retry_does_not_repeat_targets_that_already_succeeded(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    discord_id = await _make_target(database, "discord")
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    dispatcher = NotificationDispatcher(
        database=database, targets=FakeTargetRegistry({ntfy_id: ntfy, discord_id: discord})
    )
    listing = await _create_dispatchable_listing(
        database,
        search_data,
        listing_factory,
        "retry-no-duplicates",
        notification_target_ids=[ntfy_id, discord_id],
    )

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_new_listing(listing)
    assert ntfy.attempts == 1

    discord.failing = False
    await dispatcher.notify_new_listing(listing)

    assert ntfy.attempts == 1
    assert ntfy.sent == ["retry-no-duplicates"]
    assert discord.attempts == 2
    assert discord.sent == ["retry-no-duplicates"]


@pytest.mark.asyncio
async def test_search_can_reference_a_subset_of_targets(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    discord_id = await _make_target(database, "discord")
    ntfy = RecordingChannel()
    discord = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, targets=FakeTargetRegistry({ntfy_id: ntfy, discord_id: discord})
    )
    listing = await _create_dispatchable_listing(
        database,
        search_data,
        listing_factory,
        "discord-off",
        notification_target_ids=[ntfy_id],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["discord-off"]
    assert discord.attempts == 0
    state = await database.load_target_dispatch_state("discord-off")
    assert state is not None
    assert state.target_statuses[ntfy_id] == "sent"


@pytest.mark.asyncio
async def test_disabled_target_is_skipped_without_error(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    email_id = await _make_target(database, "email", enabled=False)
    ntfy = RecordingChannel()
    email = RecordingChannel(enabled=False)
    dispatcher = NotificationDispatcher(
        database=database, targets=FakeTargetRegistry({ntfy_id: ntfy, email_id: email})
    )
    listing = await _create_dispatchable_listing(
        database,
        search_data,
        listing_factory,
        "email-target-disabled",
        notification_target_ids=[ntfy_id, email_id],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["email-target-disabled"]
    assert email.attempts == 0


@pytest.mark.asyncio
async def test_deleted_target_referenced_by_a_search_is_skipped_without_error(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy_id = await _make_target(database, "ntfy")
    # The registry simply never has a live service for a deleted target id.
    dispatcher = NotificationDispatcher(database=database, targets=FakeTargetRegistry({}))
    listing = await _create_dispatchable_listing(
        database,
        search_data,
        listing_factory,
        "target-deleted",
        notification_target_ids=[ntfy_id],
    )

    await dispatcher.notify_new_listing(listing)

    state = await database.load_target_dispatch_state("target-deleted")
    assert state is not None
    assert state.target_statuses[ntfy_id] == "skipped"


@pytest.mark.asyncio
async def test_dispatch_for_unknown_listing_is_a_noop(
    database: Database,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    dispatcher = NotificationDispatcher(database=database, targets=FakeTargetRegistry({1: ntfy}))

    await dispatcher.notify_new_listing(listing_factory("never-persisted"))

    assert ntfy.attempts == 0


@pytest.mark.asyncio
async def test_dispatcher_enabled_reflects_any_target_being_enabled() -> None:
    dispatcher = NotificationDispatcher(
        database=None,  # type: ignore[arg-type]
        targets=FakeTargetRegistry(
            {1: RecordingChannel(enabled=False), 2: RecordingChannel(enabled=True)}
        ),
    )
    assert dispatcher.enabled is True

    all_disabled = NotificationDispatcher(
        database=None,  # type: ignore[arg-type]
        targets=FakeTargetRegistry({1: RecordingChannel(enabled=False)}),
    )
    assert all_disabled.enabled is False


@pytest.mark.asyncio
async def test_notify_test_target_reports_failure(database: Database) -> None:
    failing = RecordingChannel(failing=True)
    dispatcher = NotificationDispatcher(database=database, targets=FakeTargetRegistry({1: failing}))

    with pytest.raises(RuntimeError):
        await dispatcher.notify_test_target(1)

    assert failing.attempts == 1


@pytest.mark.asyncio
async def test_notify_test_target_rejects_unknown_target(database: Database) -> None:
    dispatcher = NotificationDispatcher(database=database, targets=FakeTargetRegistry({}))

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_test_target(999)
