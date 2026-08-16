import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from agent.app.core.models import EnrichmentStatus, Listing, SellerType
from agent.app.storage.database import Database, SearchCreateData


@pytest.mark.asyncio
async def test_initialize_migrates_m2_notification_table(tmp_path: Path) -> None:
    path = tmp_path / "m2.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                listing_id INTEGER NOT NULL UNIQUE,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO notifications(listing_id, status, created_at)
            VALUES (1, 'pending', '2026-01-01T00:00:00+00:00')
            """
        )

    database = Database(path)
    await database.initialize()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(notifications)")}
        migrated = connection.execute(
            "SELECT updated_at, attempt_count, last_error FROM notifications"
        ).fetchone()
    assert {"updated_at", "last_attempt_at", "attempt_count", "last_error"} <= columns
    assert migrated == ("2026-01-01T00:00:00+00:00", 0, None)


@pytest.mark.asyncio
async def test_initialize_migrates_existing_m3_listings_without_data_loss(
    tmp_path: Path,
) -> None:
    path = tmp_path / "m3.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider_listing_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                price TEXT,
                url TEXT NOT NULL,
                image_url TEXT,
                category TEXT NOT NULL,
                location TEXT,
                attributes_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO listings(
                provider_listing_id, title, url, category, location,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "m3-listing",
                "Bestehendes Inserat",
                "https://example.test/m3-listing",
                "marketplace",
                "Wien",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )

    await Database(path).initialize()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(listings)")}
        migrated = connection.execute(
            """
            SELECT provider_listing_id, title, location, seller_name, seller_type,
                   condition, enrichment_status
            FROM listings
            """
        ).fetchone()
    assert {"seller_name", "seller_type", "condition", "enrichment_status"} <= columns
    assert migrated == (
        "m3-listing",
        "Bestehendes Inserat",
        "Wien",
        None,
        None,
        None,
        "not_requested",
    )


@pytest.mark.asyncio
async def test_search_upsert_does_not_overwrite_completed_enrichment(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    base = listing_factory("preserve-enrichment", location="Wien")
    await database.persist_cycle_results([(search, [base])])
    enriched = base.model_copy(
        update={
            "location": "Wien, 22. Bezirk",
            "seller_name": "Max M.",
            "seller_type": SellerType.PRIVATE,
            "condition": "Sehr gut",
            "enrichment_status": EnrichmentStatus.ENRICHED,
            "attributes": {"published_at": "2026-08-13T08:05:00Z"},
        }
    )
    await database.update_listing_enrichment(enriched)

    current_search = await database.get_search(search.id)
    assert current_search is not None
    await database.persist_cycle_results([(current_search, [base])])

    recent = (await database.list_recent_listings(limit=1))[0]
    assert recent.location == "Wien, 22. Bezirk"
    assert recent.seller_name == "Max M."
    assert recent.condition == "Sehr gut"
    assert recent.enrichment_status is EnrichmentStatus.ENRICHED


@pytest.mark.asyncio
async def test_database_constraints_prevent_duplicate_listings(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    listing = listing_factory("unique-id")
    await database.persist_cycle_results([(search, [listing])])

    with pytest.raises(sqlite3.IntegrityError):
        await database.raw_execute(
            """
            INSERT INTO listings (
                provider_listing_id, title, url, category, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "unique-id",
                "Duplicate",
                "https://example.test/duplicate",
                "marketplace",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )


@pytest.mark.asyncio
async def test_database_constraints_prevent_duplicate_search_matches(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    listing = listing_factory("match-id")
    await database.persist_cycle_results([(search, [listing])])

    with pytest.raises(sqlite3.IntegrityError):
        await database.raw_execute(
            """
            INSERT INTO search_matches(search_id, listing_id, first_seen_at)
            VALUES (?, (SELECT id FROM listings WHERE provider_listing_id = ?), ?)
            """,
            (search.id, "match-id", "2026-01-01T00:00:00+00:00"),
        )


@pytest.mark.asyncio
async def test_reactivation_preserves_baseline_but_filter_change_resets_it(
    database: Database,
    search_data: SearchCreateData,
) -> None:
    search = await database.create_search(search_data)
    await database.persist_cycle_results([(search, [])])
    initialized = await database.get_search(search.id)
    assert initialized is not None
    assert initialized.baseline_initialized is True

    disabled = await database.update_search(search.id, {"enabled": False})
    assert disabled is not None
    assert disabled.baseline_initialized is True
    reactivated = await database.update_search(search.id, {"enabled": True})
    assert reactivated is not None
    assert reactivated.baseline_initialized is True

    changed = await database.update_search(search.id, {"query": "BMW Touring"})
    assert changed is not None
    assert changed.baseline_initialized is False


@pytest.mark.asyncio
async def test_initialize_migrates_legacy_searches_with_notification_channel_defaults(
    tmp_path: Path,
) -> None:
    path = tmp_path / "legacy-searches.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                query_json TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                baseline_initialized INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_checked_at TEXT,
                last_success_at TEXT,
                consecutive_errors INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            INSERT INTO searches(name, category, query_json, created_at, updated_at)
            VALUES ('Legacy', 'marketplace', '{}', '2026-01-01T00:00:00+00:00',
                    '2026-01-01T00:00:00+00:00')
            """
        )

    await Database(path).initialize()

    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(searches)")}
        migrated = connection.execute(
            "SELECT notify_ntfy, notify_discord, notify_email, notify_desktop_sound FROM searches"
        ).fetchone()
    assert {
        "notify_ntfy",
        "notify_discord",
        "notify_email",
        "notify_desktop_sound",
    } <= columns
    assert migrated == (1, 1, 1, 1)


@pytest.mark.asyncio
async def test_channel_delivery_status_persists_and_is_not_overwritten_after_sent(
    database: Database,
    search_data: SearchCreateData,
    listing_factory: Callable[..., Listing],
) -> None:
    search = await database.create_search(search_data)
    await database.persist_cycle_results([(search, [])])
    initialized = await database.get_search(search.id)
    assert initialized is not None
    listing = listing_factory("channel-status")
    await database.persist_cycle_results([(initialized, [listing])])

    state = await database.load_channel_dispatch_state("channel-status")
    assert state is not None
    assert state.enabled_channels == {"ntfy", "discord", "email"}
    assert state.channel_statuses == {}

    await database.record_channel_delivery_attempt(
        state.listing_id, "ntfy", sent=False, error="boom"
    )
    failed_state = await database.load_channel_dispatch_state("channel-status")
    assert failed_state is not None
    assert failed_state.channel_statuses["ntfy"] == "failed"

    await database.record_channel_delivery_attempt(state.listing_id, "ntfy", sent=True)
    sent_state = await database.load_channel_dispatch_state("channel-status")
    assert sent_state is not None
    assert sent_state.channel_statuses["ntfy"] == "sent"

    await database.record_channel_delivery_skipped(state.listing_id, "ntfy")
    unchanged_state = await database.load_channel_dispatch_state("channel-status")
    assert unchanged_state is not None
    assert unchanged_state.channel_statuses["ntfy"] == "sent"
