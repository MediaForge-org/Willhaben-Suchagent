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

from agent.app.core.article_label import derive_article_label
from agent.app.core.models import (
    EnrichmentStatus,
    Listing,
    MessageTemplate,
    SearchCategory,
    SearchDefinition,
    SellerType,
)
from agent.app.core.templates import DEFAULT_TEMPLATE_BODY, DEFAULT_TEMPLATE_NAME
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
    default_template_id: int | None = None


@dataclass(slots=True)
class TemplateCreateData:
    name: str
    body: str


@dataclass(slots=True)
class CyclePersistenceResult:
    created_notification_count: int
    new_listing_count: int
    baseline_initializations: int


@dataclass(slots=True)
class PendingNotification:
    id: int
    listing: Listing
    status: str
    attempt_count: int


@dataclass(slots=True)
class RecentListing:
    id: int
    provider_listing_id: str
    title: str
    article_label: str
    price: Decimal | None
    location: str | None
    image_url: str | None
    seller_name: str | None
    seller_type: SellerType | None
    condition: str | None
    enrichment_status: EnrichmentStatus
    url: str
    first_seen_at: datetime
    search_ids: list[int]
    search_names: list[str]


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
            await self._migrate_searches(connection)
            await self._migrate_listings(connection)
            await self._migrate_notifications(connection)
            await self._ensure_default_template(connection)
            await connection.commit()

    @staticmethod
    async def _migrate_searches(connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA table_info(searches)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "default_template_id" not in columns:
            await connection.execute(
                "ALTER TABLE searches ADD COLUMN default_template_id INTEGER "
                "REFERENCES message_templates(id) ON DELETE SET NULL"
            )

    @staticmethod
    async def _migrate_listings(connection: aiosqlite.Connection) -> None:
        """Add M3.1 enrichment fields without replacing an existing M1-M3 database."""

        cursor = await connection.execute("PRAGMA table_info(listings)")
        columns = {row[1] for row in await cursor.fetchall()}
        additions = {
            "article_label": "TEXT NOT NULL DEFAULT 'der Artikel'",
            "seller_name": "TEXT",
            "seller_type": "TEXT",
            "condition": "TEXT",
            "enrichment_status": "TEXT NOT NULL DEFAULT 'not_requested'",
        }
        for name, definition in additions.items():
            if name not in columns:
                await connection.execute(
                    f"ALTER TABLE listings ADD COLUMN {name} {definition}"  # noqa: S608
                )
        cursor = await connection.execute(
            "SELECT id, title, attributes_json, article_label FROM listings"
        )
        for row in await cursor.fetchall():
            if row["article_label"] != "der Artikel":
                continue
            try:
                attributes = json.loads(row["attributes_json"] or "{}")
            except json.JSONDecodeError:
                attributes = {}
            await connection.execute(
                "UPDATE listings SET article_label = ? WHERE id = ?",
                (derive_article_label(row["title"], attributes), row["id"]),
            )

    @staticmethod
    async def _ensure_default_template(connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("SELECT COUNT(*) FROM message_templates")
        row = await cursor.fetchone()
        if row and row[0] == 0:
            timestamp = to_db_timestamp()
            await connection.execute(
                """
                INSERT INTO message_templates(name, body, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (DEFAULT_TEMPLATE_NAME, DEFAULT_TEMPLATE_BODY, timestamp, timestamp),
            )

    @staticmethod
    async def _migrate_notifications(connection: aiosqlite.Connection) -> None:
        """Add M3 delivery fields to databases created by M1/M2."""

        cursor = await connection.execute("PRAGMA table_info(notifications)")
        columns = {row[1] for row in await cursor.fetchall()}
        additions = {
            "updated_at": "TEXT",
            "last_attempt_at": "TEXT",
            "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "last_error": "TEXT",
        }
        for name, definition in additions.items():
            if name not in columns:
                await connection.execute(
                    f"ALTER TABLE notifications ADD COLUMN {name} {definition}"  # noqa: S608
                )
        await connection.execute(
            "UPDATE notifications SET updated_at = created_at WHERE updated_at IS NULL"
        )

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
            default_template_id=row["default_template_id"],
            **query_data,
        )

    async def create_search(self, data: SearchCreateData) -> SearchDefinition:
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO searches (
                    name, category, query_json, enabled, baseline_initialized,
                    created_at, updated_at, default_template_id
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (
                    data.name,
                    data.category.value,
                    self._query_json(data),
                    int(data.enabled),
                    timestamp,
                    timestamp,
                    data.default_template_id,
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
            "default_template_id",
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
        reset_baseline = bool(reset_fields.intersection(changes))
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE searches
                SET name = ?, category = ?, query_json = ?, enabled = ?,
                    baseline_initialized = ?, updated_at = ?, default_template_id = ?
                WHERE id = ?
                """,
                (
                    validated.name,
                    validated.category.value,
                    self._query_json(validated),
                    int(validated.enabled),
                    0 if reset_baseline else int(current.baseline_initialized),
                    timestamp,
                    validated.default_template_id,
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
        new_provider_ids: set[str] = set()
        notification_candidates: dict[str, Listing] = {}
        baseline_initializations = 0
        created_notification_count = 0

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
                                provider_listing_id, title, article_label, price, url, image_url,
                                category, location, seller_name, seller_type, condition,
                                enrichment_status, attributes_json, first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(provider_listing_id) DO UPDATE SET
                                title = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.title ELSE excluded.title END,
                                article_label = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.article_label ELSE excluded.article_label END,
                                price = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.price ELSE excluded.price END,
                                url = excluded.url,
                                image_url = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.image_url ELSE excluded.image_url END,
                                category = excluded.category,
                                location = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.location ELSE excluded.location END,
                                attributes_json = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.attributes_json ELSE excluded.attributes_json END,
                                last_seen_at = excluded.last_seen_at
                            """,
                            (
                                listing.provider_listing_id,
                                listing.title,
                                listing.article_label,
                                str(listing.price) if listing.price is not None else None,
                                str(listing.url),
                                str(listing.image_url) if listing.image_url else None,
                                listing.category.value,
                                listing.location,
                                listing.seller_name,
                                listing.seller_type.value if listing.seller_type else None,
                                listing.condition,
                                listing.enrichment_status.value,
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

                for provider_id in notification_candidates:
                    cursor = await connection.execute(
                        "SELECT id FROM listings WHERE provider_listing_id = ?",
                        (provider_id,),
                    )
                    listing_row = await cursor.fetchone()
                    insert_cursor = await connection.execute(
                        """
                        INSERT OR IGNORE INTO notifications(
                            listing_id, status, created_at, updated_at
                        )
                        VALUES (?, 'pending', ?, ?)
                        """,
                        (listing_row["id"], timestamp, timestamp),
                    )
                    if insert_cursor.rowcount > 0:
                        created_notification_count += 1
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

        return CyclePersistenceResult(
            created_notification_count=created_notification_count,
            new_listing_count=len(new_provider_ids),
            baseline_initializations=baseline_initializations,
        )

    async def update_listing_enrichment(self, listing: Listing) -> None:
        """Persist one completed, partial, or failed one-shot enrichment attempt."""

        if listing.enrichment_status is EnrichmentStatus.NOT_REQUESTED:
            raise ValueError("Enrichment update must have a terminal status")
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                """
                UPDATE listings
                SET title = ?, price = ?, image_url = ?, location = ?, seller_name = ?,
                    seller_type = ?, condition = ?, enrichment_status = ?, attributes_json = ?,
                    article_label = ?
                WHERE provider_listing_id = ? AND enrichment_status = 'not_requested'
                """,
                (
                    listing.title,
                    str(listing.price) if listing.price is not None else None,
                    str(listing.image_url) if listing.image_url else None,
                    listing.location,
                    listing.seller_name,
                    listing.seller_type.value if listing.seller_type else None,
                    listing.condition,
                    listing.enrichment_status.value,
                    json.dumps(listing.attributes, separators=(",", ":"), sort_keys=True),
                    listing.article_label,
                    listing.provider_listing_id,
                ),
            )
            if cursor.rowcount == 0:
                cursor = await connection.execute(
                    "SELECT enrichment_status FROM listings WHERE provider_listing_id = ?",
                    (listing.provider_listing_id,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Listing selected for enrichment no longer exists")
            await connection.commit()

    async def list_deliverable_notifications(self) -> list[PendingNotification]:
        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT
                    notifications.id AS notification_id,
                    notifications.status,
                    notifications.attempt_count,
                    listings.provider_listing_id,
                    listings.title,
                    listings.article_label,
                    listings.price,
                    listings.url,
                    listings.image_url,
                    listings.category,
                    listings.location,
                    listings.seller_name,
                    listings.seller_type,
                    listings.condition,
                    listings.enrichment_status,
                    listings.attributes_json
                FROM notifications
                JOIN listings ON listings.id = notifications.listing_id
                WHERE notifications.status IN ('pending', 'failed')
                ORDER BY notifications.created_at, notifications.id
                """
            )
            rows = await cursor.fetchall()
        return [
            PendingNotification(
                id=row["notification_id"],
                status=row["status"],
                attempt_count=row["attempt_count"],
                listing=Listing(
                    provider_listing_id=row["provider_listing_id"],
                    title=row["title"],
                    article_label=row["article_label"],
                    price=Decimal(row["price"]) if row["price"] is not None else None,
                    url=row["url"],
                    image_url=row["image_url"],
                    category=row["category"],
                    location=row["location"],
                    seller_name=row["seller_name"],
                    seller_type=row["seller_type"],
                    condition=row["condition"],
                    enrichment_status=row["enrichment_status"],
                    attributes=json.loads(row["attributes_json"]),
                ),
            )
            for row in rows
        ]

    async def mark_notification_sent(self, notification_id: int) -> None:
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE notifications
                SET status = 'sent', sent_at = ?, updated_at = ?, last_attempt_at = ?,
                    attempt_count = attempt_count + 1, last_error = NULL
                WHERE id = ? AND status IN ('pending', 'failed')
                """,
                (timestamp, timestamp, timestamp, notification_id),
            )
            await connection.commit()

    async def mark_notification_failed(self, notification_id: int, error: str) -> None:
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE notifications
                SET status = 'failed', updated_at = ?, last_attempt_at = ?,
                    attempt_count = attempt_count + 1, last_error = ?
                WHERE id = ? AND status IN ('pending', 'failed')
                """,
                (timestamp, timestamp, error[:1000], notification_id),
            )
            await connection.commit()

    async def notification_status(self, provider_listing_id: str) -> dict[str, Any] | None:
        async with self._connect() as connection:
            cursor = await connection.execute(
                """
                SELECT notifications.*
                FROM notifications
                JOIN listings ON listings.id = notifications.listing_id
                WHERE listings.provider_listing_id = ?
                """,
                (provider_listing_id,),
            )
            row = await cursor.fetchone()
        return dict(row) if row else None

    async def count_notifications_with_status(self, status: str) -> int:
        if status not in {"pending", "sent", "failed"}:
            raise ValueError(f"Unsupported notification status: {status}")
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE status = ?",
                (status,),
            )
            row = await cursor.fetchone()
        return int(row[0])

    async def last_successful_notification_at(self) -> datetime | None:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT MAX(sent_at) FROM notifications WHERE status = 'sent'"
            )
            row = await cursor.fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    async def list_recent_listings(
        self,
        *,
        limit: int,
        search_id: int | None = None,
    ) -> list[RecentListing]:
        parameters: list[Any] = []
        condition = ""
        if search_id is not None:
            condition = (
                "WHERE EXISTS ("
                "SELECT 1 FROM search_matches selected_match "
                "WHERE selected_match.listing_id = listings.id "
                "AND selected_match.search_id = ?"
                ")"
            )
            parameters.append(search_id)
        parameters.append(limit)
        async with self._connect() as connection:
            cursor = await connection.execute(
                f"""
                SELECT listings.*
                FROM listings
                {condition}
                ORDER BY listings.first_seen_at DESC, listings.id DESC
                LIMIT ?
                """,  # noqa: S608
                tuple(parameters),
            )
            listing_rows = await cursor.fetchall()
            recent: list[RecentListing] = []
            for row in listing_rows:
                matches_cursor = await connection.execute(
                    """
                    SELECT searches.id, searches.name
                    FROM search_matches
                    JOIN searches ON searches.id = search_matches.search_id
                    WHERE search_matches.listing_id = ?
                    ORDER BY searches.id
                    """,
                    (row["id"],),
                )
                matches = await matches_cursor.fetchall()
                recent.append(
                    RecentListing(
                        id=row["id"],
                        provider_listing_id=row["provider_listing_id"],
                        title=row["title"],
                        article_label=row["article_label"],
                        price=Decimal(row["price"]) if row["price"] is not None else None,
                        location=row["location"],
                        image_url=row["image_url"],
                        seller_name=row["seller_name"],
                        seller_type=(
                            SellerType(row["seller_type"]) if row["seller_type"] else None
                        ),
                        condition=row["condition"],
                        enrichment_status=EnrichmentStatus(row["enrichment_status"]),
                        url=row["url"],
                        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
                        search_ids=[match["id"] for match in matches],
                        search_names=[match["name"] for match in matches],
                    )
                )
        return recent

    async def get_listing(self, listing_id: int) -> Listing | None:
        async with self._connect() as connection:
            cursor = await connection.execute("SELECT * FROM listings WHERE id = ?", (listing_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return Listing(
            provider_listing_id=row["provider_listing_id"],
            title=row["title"],
            article_label=row["article_label"],
            price=Decimal(row["price"]) if row["price"] is not None else None,
            url=row["url"],
            image_url=row["image_url"],
            category=row["category"],
            location=row["location"],
            seller_name=row["seller_name"],
            seller_type=row["seller_type"],
            condition=row["condition"],
            enrichment_status=row["enrichment_status"],
            attributes=json.loads(row["attributes_json"]),
        )

    @staticmethod
    def _row_to_template(row: aiosqlite.Row) -> MessageTemplate:
        return MessageTemplate(
            id=row["id"],
            name=row["name"],
            body=row["body"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def list_templates(self) -> list[MessageTemplate]:
        async with self._connect() as connection:
            cursor = await connection.execute("SELECT * FROM message_templates ORDER BY id")
            rows = await cursor.fetchall()
        return [self._row_to_template(row) for row in rows]

    async def get_template(self, template_id: int) -> MessageTemplate | None:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM message_templates WHERE id = ?", (template_id,)
            )
            row = await cursor.fetchone()
        return self._row_to_template(row) if row else None

    async def create_template(self, data: TemplateCreateData) -> MessageTemplate:
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO message_templates(name, body, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (data.name, data.body, timestamp, timestamp),
            )
            await connection.commit()
            template_id = cursor.lastrowid
        if template_id is None:
            raise RuntimeError("SQLite did not return a template id")
        template = await self.get_template(template_id)
        if template is None:
            raise RuntimeError("Created template could not be reloaded")
        return template

    async def update_template(
        self, template_id: int, changes: dict[str, str]
    ) -> MessageTemplate | None:
        current = await self.get_template(template_id)
        if current is None:
            return None
        name = changes.get("name", current.name)
        body = changes.get("body", current.body)
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE message_templates SET name = ?, body = ?, updated_at = ? WHERE id = ?
                """,
                (name, body, timestamp, template_id),
            )
            await connection.commit()
        return await self.get_template(template_id)

    async def delete_template(self, template_id: int) -> bool:
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                "DELETE FROM message_templates WHERE id = ?", (template_id,)
            )
            await connection.commit()
        return cursor.rowcount > 0

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
