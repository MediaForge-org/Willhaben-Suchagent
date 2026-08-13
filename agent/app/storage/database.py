from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import aiosqlite

from agent.app.core.models import Listing, SearchCategory, SearchDefinition
from agent.app.core.time import to_db_timestamp
from agent.app.storage.schema import SCHEMA


@dataclass(slots=True)
class SearchCreateData:
    name: str
    category: SearchCategory
    enabled: bool
    query: str
    location: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    category_filters: dict[str, Any]


@dataclass(slots=True)
class CyclePersistenceResult:
    notification_listings: list[Listing]
    new_listing_count: int
    baseline_initializations: int


class Database:
    """Small repository layer owning all SQLite details and transactions."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute("PRAGMA synchronous = NORMAL")
            await connection.executescript(SCHEMA)
            await connection.commit()

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with aiosqlite.connect(self.path) as connection:
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA busy_timeout = 5000")
            yield connection

    @staticmethod
    def _query_json(data: SearchCreateData | SearchDefinition) -> str:
        payload = {
            "query": data.query,
            "location": data.location,
            "price_min": str(data.price_min) if data.price_min is not None else None,
            "price_max": str(data.price_max) if data.price_max is not None else None,
            "category_filters": data.category_filters,
        }
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _row_to_search(row: aiosqlite.Row) -> SearchDefinition:
        query_data = json.loads(row["query_json"])
        return SearchDefinition(
            id=row["id"],
            name=row["name"],
            category=row["category"],
            enabled=bool(row["enabled"]),
            baseline_initialized=bool(row["baseline_initialized"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_checked_at=row["last_checked_at"],
            last_success_at=row["last_success_at"],
            consecutive_errors=row["consecutive_errors"],
            **query_data,
        )

    async def create_search(self, data: SearchCreateData) -> SearchDefinition:
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO searches (
                    name, category, query_json, enabled, baseline_initialized,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    data.name,
                    data.category.value,
                    self._query_json(data),
                    int(data.enabled),
                    timestamp,
                    timestamp,
                ),
            )
            await connection.commit()
            search_id = cursor.lastrowid
        if search_id is None:
            raise RuntimeError("SQLite did not return a search id")
        search = await self.get_search(search_id)
        if search is None:
            raise RuntimeError("Created search could not be reloaded")
        return search

    async def get_search(self, search_id: int) -> SearchDefinition | None:
        async with self._connect() as connection:
            cursor = await connection.execute("SELECT * FROM searches WHERE id = ?", (search_id,))
            row = await cursor.fetchone()
        return self._row_to_search(row) if row else None

    async def list_searches(self, *, enabled_only: bool = False) -> list[SearchDefinition]:
        query = "SELECT * FROM searches"
        parameters: tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE enabled = ?"
            parameters = (1,)
        query += " ORDER BY id"
        async with self._connect() as connection:
            cursor = await connection.execute(query, parameters)
            rows = await cursor.fetchall()
        return [self._row_to_search(row) for row in rows]

    async def update_search(
        self, search_id: int, changes: dict[str, Any]
    ) -> SearchDefinition | None:
        current = await self.get_search(search_id)
        if current is None:
            return None

        domain_fields = {
            "name",
            "category",
            "enabled",
            "query",
            "location",
            "price_min",
            "price_max",
            "category_filters",
        }
        merged = current.model_dump()
        merged.update({key: value for key, value in changes.items() if key in domain_fields})
        validated = SearchDefinition.model_validate(merged)

        reset_fields = {
            "category",
            "query",
            "location",
            "price_min",
            "price_max",
            "category_filters",
        }
        reset_baseline = bool(reset_fields.intersection(changes)) or (
            not current.enabled and validated.enabled
        )
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE searches
                SET name = ?, category = ?, query_json = ?, enabled = ?,
                    baseline_initialized = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    validated.name,
                    validated.category.value,
                    self._query_json(validated),
                    int(validated.enabled),
                    0 if reset_baseline else int(current.baseline_initialized),
                    timestamp,
                    search_id,
                ),
            )
            await connection.commit()
        return await self.get_search(search_id)

    async def delete_search(self, search_id: int) -> bool:
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute("DELETE FROM searches WHERE id = ?", (search_id,))
            await connection.commit()
        return cursor.rowcount > 0

    async def record_search_failure(self, search_id: int) -> None:
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE searches
                SET last_checked_at = ?, updated_at = ?,
                    consecutive_errors = consecutive_errors + 1
                WHERE id = ?
                """,
                (timestamp, timestamp, search_id),
            )
            await connection.commit()

    async def persist_cycle_results(
        self,
        successful_results: Iterable[tuple[SearchDefinition, list[Listing]]],
    ) -> CyclePersistenceResult:
        """Persist one cycle atomically, preserving global deduplication semantics."""

        results = list(successful_results)
        timestamp = to_db_timestamp()
        notification_listings: list[Listing] = []
        new_provider_ids: set[str] = set()
        notification_candidates: dict[str, Listing] = {}
        baseline_initializations = 0

        async with self._write_lock, self._connect() as connection:
            await connection.execute("BEGIN IMMEDIATE")
            try:
                current_results: list[tuple[SearchDefinition, list[Listing]]] = []
                for search, listings in results:
                    cursor = await connection.execute(
                        "SELECT enabled, updated_at FROM searches WHERE id = ?",
                        (search.id,),
                    )
                    current_row = await cursor.fetchone()
                    if (
                        current_row is not None
                        and bool(current_row["enabled"])
                        and datetime.fromisoformat(current_row["updated_at"]) == search.updated_at
                    ):
                        current_results.append((search, listings))
                results = current_results
                baseline_initializations = sum(
                    not search.baseline_initialized for search, _ in results
                )

                provider_ids = {
                    listing.provider_listing_id for _, listings in results for listing in listings
                }
                existing_ids: set[str] = set()
                provider_id_list = list(provider_ids)
                for offset in range(0, len(provider_id_list), 500):
                    chunk = provider_id_list[offset : offset + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    cursor = await connection.execute(
                        f"SELECT provider_listing_id FROM listings "  # noqa: S608
                        f"WHERE provider_listing_id IN ({placeholders})",
                        tuple(chunk),
                    )
                    existing_ids.update(row[0] for row in await cursor.fetchall())
                new_provider_ids = provider_ids - existing_ids

                for search, listings in results:
                    for listing in listings:
                        await connection.execute(
                            """
                            INSERT INTO listings (
                                provider_listing_id, title, price, url, image_url,
                                category, location, attributes_json, first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(provider_listing_id) DO UPDATE SET
                                title = excluded.title,
                                price = excluded.price,
                                url = excluded.url,
                                image_url = excluded.image_url,
                                category = excluded.category,
                                location = excluded.location,
                                attributes_json = excluded.attributes_json,
                                last_seen_at = excluded.last_seen_at
                            """,
                            (
                                listing.provider_listing_id,
                                listing.title,
                                str(listing.price) if listing.price is not None else None,
                                str(listing.url),
                                str(listing.image_url) if listing.image_url else None,
                                listing.category.value,
                                listing.location,
                                json.dumps(
                                    listing.attributes,
                                    separators=(",", ":"),
                                    sort_keys=True,
                                ),
                                timestamp,
                                timestamp,
                            ),
                        )
                        cursor = await connection.execute(
                            "SELECT id FROM listings WHERE provider_listing_id = ?",
                            (listing.provider_listing_id,),
                        )
                        listing_row = await cursor.fetchone()
                        if listing_row is None:
                            raise RuntimeError("Upserted listing could not be loaded")
                        await connection.execute(
                            """
                            INSERT OR IGNORE INTO search_matches(
                                search_id, listing_id, first_seen_at
                            )
                            VALUES (?, ?, ?)
                            """,
                            (search.id, listing_row["id"], timestamp),
                        )
                        if (
                            search.baseline_initialized
                            and listing.provider_listing_id in new_provider_ids
                        ):
                            notification_candidates[listing.provider_listing_id] = listing

                    await connection.execute(
                        """
                        UPDATE searches
                        SET baseline_initialized = 1, last_checked_at = ?,
                            last_success_at = ?, consecutive_errors = 0, updated_at = ?
                        WHERE id = ?
                        """,
                        (timestamp, timestamp, timestamp, search.id),
                    )

                for provider_id, listing in notification_candidates.items():
                    cursor = await connection.execute(
                        "SELECT id FROM listings WHERE provider_listing_id = ?",
                        (provider_id,),
                    )
                    listing_row = await cursor.fetchone()
                    insert_cursor = await connection.execute(
                        """
                        INSERT OR IGNORE INTO notifications(listing_id, status, created_at)
                        VALUES (?, 'pending', ?)
                        """,
                        (listing_row["id"], timestamp),
                    )
                    if insert_cursor.rowcount > 0:
                        notification_listings.append(listing)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

        return CyclePersistenceResult(
            notification_listings=notification_listings,
            new_listing_count=len(new_provider_ids),
            baseline_initializations=baseline_initializations,
        )

    async def mark_notification_sent(self, provider_listing_id: str) -> None:
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE notifications
                SET status = 'sent', sent_at = ?
                WHERE listing_id = (
                    SELECT id FROM listings WHERE provider_listing_id = ?
                )
                """,
                (to_db_timestamp(), provider_listing_id),
            )
            await connection.commit()

    async def count(self, table: str) -> int:
        allowed_tables = {"searches", "listings", "search_matches", "notifications"}
        if table not in allowed_tables:
            raise ValueError(f"Unsupported table: {table}")
        async with self._connect() as connection:
            cursor = await connection.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            row = await cursor.fetchone()
        return int(row[0])

    async def status_counts(self) -> dict[str, int]:
        return {
            table: await self.count(table)
            for table in ("searches", "listings", "search_matches", "notifications")
        }

    async def raw_execute(self, query: str, parameters: tuple[Any, ...] = ()) -> None:
        """Execute a statement for focused constraint tests and migrations tooling."""

        async with self._write_lock, self._connect() as connection:
            await connection.execute(query, parameters)
            await connection.commit()
