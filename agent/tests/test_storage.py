import sqlite3
from collections.abc import Callable

import pytest

from agent.app.core.models import Listing
from agent.app.storage.database import Database, SearchCreateData


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
async def test_reactivation_and_filter_change_reset_baseline(
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
    assert reactivated.baseline_initialized is False

    await database.persist_cycle_results([(reactivated, [])])
    changed = await database.update_search(search.id, {"query": "BMW Touring"})
    assert changed is not None
    assert changed.baseline_initialized is False
