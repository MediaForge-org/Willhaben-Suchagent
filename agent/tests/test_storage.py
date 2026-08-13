import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from agent.app.core.models import Listing
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
