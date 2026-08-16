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
async def test_two_searches_with_different_channel_toggles_union_to_one_delivery_each(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    """Search A wants ntfy only, Search B wants Discord+E-Mail only; both match one listing."""

    ntfy, discord, email = RecordingChannel(), RecordingChannel(), RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, channels={"ntfy": ntfy, "discord": discord, "email": email}
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "cross-search-union",
        [
            {"notify_ntfy": True, "notify_discord": False, "notify_email": False},
            {"notify_ntfy": False, "notify_discord": True, "notify_email": True},
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
async def test_same_channel_enabled_by_both_matching_searches_still_delivers_exactly_once(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    dispatcher = NotificationDispatcher(database=database, channels={"ntfy": ntfy})
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "both-want-ntfy",
        [{"notify_ntfy": True}, {"notify_ntfy": True}],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.attempts == 1
    assert ntfy.sent == ["both-want-ntfy"]


@pytest.mark.asyncio
async def test_channel_disabled_by_every_matching_search_is_skipped_not_delivered(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    dispatcher = NotificationDispatcher(database=database, channels={"ntfy": ntfy})
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "both-refuse-ntfy",
        [{"notify_ntfy": False}, {"notify_ntfy": False}],
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.attempts == 0
    state = await database.load_channel_dispatch_state("both-refuse-ntfy")
    assert state is not None
    assert state.channel_statuses["ntfy"] == "skipped"


@pytest.mark.asyncio
async def test_one_channel_failure_across_a_shared_listing_does_not_block_others(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    email = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, channels={"ntfy": ntfy, "discord": discord, "email": email}
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "shared-partial-outage",
        [
            {"notify_ntfy": True, "notify_discord": True, "notify_email": False},
            {"notify_ntfy": False, "notify_discord": True, "notify_email": True},
        ],
    )

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["shared-partial-outage"]
    assert email.sent == ["shared-partial-outage"]
    assert discord.attempts == 1
    assert discord.sent == []


@pytest.mark.asyncio
async def test_retry_after_shared_listing_failure_only_repeats_the_failed_channel(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    email = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, channels={"ntfy": ntfy, "discord": discord, "email": email}
    )
    listing = await _create_listing_matched_by_searches(
        database,
        search_data,
        listing_factory,
        "shared-retry",
        [
            {"notify_ntfy": True, "notify_discord": True, "notify_email": False},
            {"notify_ntfy": False, "notify_discord": True, "notify_email": True},
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
async def test_dispatcher_delivers_to_all_enabled_channels(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy, discord, email = RecordingChannel(), RecordingChannel(), RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        channels={"ntfy": ntfy, "discord": discord, "email": email},
    )
    listing = await _create_dispatchable_listing(
        database, search_data, listing_factory, "multi-channel"
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["multi-channel"]
    assert discord.sent == ["multi-channel"]
    assert email.sent == ["multi-channel"]


@pytest.mark.asyncio
async def test_channel_outage_does_not_block_other_channels(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    email = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database,
        channels={"ntfy": ntfy, "discord": discord, "email": email},
    )
    listing = await _create_dispatchable_listing(
        database, search_data, listing_factory, "partial-outage"
    )

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["partial-outage"]
    assert email.sent == ["partial-outage"]
    assert discord.attempts == 1


@pytest.mark.asyncio
async def test_retry_does_not_repeat_channels_that_already_succeeded(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    dispatcher = NotificationDispatcher(
        database=database, channels={"ntfy": ntfy, "discord": discord}
    )
    listing = await _create_dispatchable_listing(
        database, search_data, listing_factory, "retry-no-duplicates"
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
async def test_search_can_disable_one_channel_independently(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    discord = RecordingChannel()
    dispatcher = NotificationDispatcher(
        database=database, channels={"ntfy": ntfy, "discord": discord}
    )
    listing = await _create_dispatchable_listing(
        database,
        search_data,
        listing_factory,
        "discord-off",
        notify_discord=False,
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["discord-off"]
    assert discord.attempts == 0
    state = await database.load_channel_dispatch_state("discord-off")
    assert state is not None
    assert state.channel_statuses["ntfy"] == "sent"
    assert state.channel_statuses["discord"] == "skipped"


@pytest.mark.asyncio
async def test_globally_disabled_channel_is_skipped_without_error(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    email = RecordingChannel(enabled=False)
    dispatcher = NotificationDispatcher(database=database, channels={"ntfy": ntfy, "email": email})
    listing = await _create_dispatchable_listing(
        database, search_data, listing_factory, "email-globally-off"
    )

    await dispatcher.notify_new_listing(listing)

    assert ntfy.sent == ["email-globally-off"]
    assert email.attempts == 0


@pytest.mark.asyncio
async def test_dispatch_for_unknown_listing_is_a_noop(
    database: Database,
    listing_factory: Callable[..., Listing],
) -> None:
    ntfy = RecordingChannel()
    dispatcher = NotificationDispatcher(database=database, channels={"ntfy": ntfy})

    await dispatcher.notify_new_listing(listing_factory("never-persisted"))

    assert ntfy.attempts == 0


@pytest.mark.asyncio
async def test_dispatcher_enabled_reflects_any_channel_being_enabled(
    database: Database,
) -> None:
    dispatcher = NotificationDispatcher(
        database=database,
        channels={"ntfy": RecordingChannel(enabled=False), "discord": RecordingChannel()},
    )
    assert dispatcher.enabled is True

    all_disabled = NotificationDispatcher(
        database=database,
        channels={"ntfy": RecordingChannel(enabled=False)},
    )
    assert all_disabled.enabled is False
    assert "disabled for test" in (all_disabled.disabled_reason or "")


@pytest.mark.asyncio
async def test_notify_test_aggregates_channel_failures(database: Database) -> None:
    ntfy = RecordingChannel()
    discord = RecordingChannel(failing=True)
    dispatcher = NotificationDispatcher(
        database=database, channels={"ntfy": ntfy, "discord": discord}
    )

    with pytest.raises(NotificationDeliveryError):
        await dispatcher.notify_test()

    assert ntfy.attempts == 1
    assert discord.attempts == 1
