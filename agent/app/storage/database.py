from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import aiosqlite

from agent.app.core.article_label import derive_article_label, derive_article_phrase
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
from agent.app.notifications.sound import DEFAULT_SOUND_ID, SOUND_VARIANTS
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
    notification_target_ids: list[int] = field(default_factory=list)
    notify_desktop_sound: bool = True


@dataclass(slots=True)
class TemplateCreateData:
    name: str
    body: str


@dataclass(frozen=True, slots=True)
class DesktopSoundPreferences:
    enabled: bool
    sound_id: str


@dataclass(frozen=True, slots=True)
class NotificationSettingsRecord:
    """Global, provider-technical notification settings.

    Per-destination configuration (which ntfy topic, which Discord webhook, which
    e-mail recipient) lives in ``notification_targets`` instead — see
    NotificationTargetRecord. Only the SMTP *sender* account and per-channel
    request timeouts stay global, since they are shared by every target of that
    type rather than being a property of any one destination.
    """

    ntfy_timeout_seconds: float
    discord_timeout_seconds: float
    email_smtp_host: str | None
    email_smtp_port: int
    email_smtp_username: str | None
    email_from_address: str | None
    email_encryption: str
    email_timeout_seconds: float


_NOTIFICATION_SETTINGS_BOOL_KEYS: tuple[str, ...] = ()
_NOTIFICATION_SETTINGS_INT_KEYS = ("email_smtp_port",)
_NOTIFICATION_SETTINGS_FLOAT_KEYS = (
    "ntfy_timeout_seconds",
    "discord_timeout_seconds",
    "email_timeout_seconds",
)
_NOTIFICATION_SETTINGS_KEYS = tuple(NotificationSettingsRecord.__dataclass_fields__)


def _default_notification_settings() -> NotificationSettingsRecord:
    return NotificationSettingsRecord(
        ntfy_timeout_seconds=10,
        discord_timeout_seconds=10,
        email_smtp_host=None,
        email_smtp_port=587,
        email_smtp_username=None,
        email_from_address=None,
        email_encryption="starttls",
        email_timeout_seconds=10,
    )


def _encode_notification_setting(key: str, value: Any) -> str:
    if key in _NOTIFICATION_SETTINGS_BOOL_KEYS:
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)


def _decode_notification_setting(key: str, raw: str | None) -> Any:
    if raw is None or raw == "":
        return None
    if key in _NOTIFICATION_SETTINGS_BOOL_KEYS:
        return raw == "1"
    if key in _NOTIFICATION_SETTINGS_INT_KEYS:
        return int(raw)
    if key in _NOTIFICATION_SETTINGS_FLOAT_KEYS:
        return float(raw)
    return raw


def _notification_settings_to_raw(record: NotificationSettingsRecord) -> dict[str, str]:
    return {
        key: _encode_notification_setting(key, getattr(record, key))
        for key in _NOTIFICATION_SETTINGS_KEYS
    }


def _raw_to_notification_settings(raw: dict[str, str]) -> NotificationSettingsRecord:
    defaults = _default_notification_settings()
    values: dict[str, Any] = {}
    for key in _NOTIFICATION_SETTINGS_KEYS:
        decoded = _decode_notification_setting(key, raw.get(key))
        values[key] = decoded if decoded is not None else getattr(defaults, key)
    return NotificationSettingsRecord(**values)


@dataclass(slots=True)
class CyclePersistenceResult:
    created_notification_count: int
    new_listing_count: int
    baseline_initializations: int
    desktop_sound_requested: bool = False


@dataclass(slots=True)
class PendingNotification:
    id: int
    listing: Listing
    status: str
    attempt_count: int


NOTIFICATION_TARGET_TYPES: tuple[str, ...] = ("ntfy", "discord", "email")


@dataclass(frozen=True, slots=True)
class NotificationTargetRecord:
    id: int
    type: str
    name: str
    enabled: bool
    ntfy_base_url: str | None
    email_address: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class TargetDispatchState:
    listing_id: int
    target_ids: set[int]
    target_statuses: dict[int, str]


@dataclass(slots=True)
class RecentListing:
    id: int
    provider_listing_id: str
    title: str
    article_label: str
    article_phrase: str
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

    async def initialize(
        self,
        *,
        desktop_sound_enabled: bool = True,
        desktop_sound_id: str = DEFAULT_SOUND_ID,
        notification_settings_seed: NotificationSettingsRecord | None = None,
    ) -> None:
        if desktop_sound_id not in SOUND_VARIANTS:
            raise ValueError(f"Unsupported desktop sound id: {desktop_sound_id}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self._connect() as connection:
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute("PRAGMA synchronous = NORMAL")
            await connection.executescript(SCHEMA)
            await self._migrate_searches(connection)
            await self._migrate_listings(connection)
            await self._migrate_notifications(connection)
            await self._ensure_default_template(connection)
            await self._ensure_agent_settings(
                connection,
                desktop_sound_enabled=desktop_sound_enabled,
                desktop_sound_id=desktop_sound_id,
            )
            await self._ensure_notification_settings(
                connection, notification_settings_seed or _default_notification_settings()
            )
            await connection.commit()

    @staticmethod
    async def _ensure_notification_settings(
        connection: aiosqlite.Connection, seed: NotificationSettingsRecord
    ) -> None:
        raw = _notification_settings_to_raw(seed)
        await connection.executemany(
            "INSERT OR IGNORE INTO agent_settings(key, value) VALUES (?, ?)",
            list(raw.items()),
        )

    async def get_notification_settings(self) -> NotificationSettingsRecord:
        async with self._connect() as connection:
            placeholders = ",".join("?" for _ in _NOTIFICATION_SETTINGS_KEYS)
            cursor = await connection.execute(
                f"SELECT key, value FROM agent_settings WHERE key IN ({placeholders})",  # noqa: S608
                _NOTIFICATION_SETTINGS_KEYS,
            )
            raw = {row["key"]: row["value"] for row in await cursor.fetchall()}
        return _raw_to_notification_settings(raw)

    async def update_notification_settings(
        self, changes: dict[str, Any]
    ) -> NotificationSettingsRecord:
        if not changes or not set(changes) <= set(_NOTIFICATION_SETTINGS_KEYS):
            raise ValueError("Unsupported notification setting key")
        current = await self.get_notification_settings()
        merged = {key: getattr(current, key) for key in _NOTIFICATION_SETTINGS_KEYS}
        merged.update(changes)
        validated = NotificationSettingsRecord(**merged)
        raw = _notification_settings_to_raw(validated)
        rows = [(key, raw[key]) for key in changes]
        async with self._write_lock, self._connect() as connection:
            await connection.executemany(
                "INSERT INTO agent_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                rows,
            )
            await connection.commit()
        return await self.get_notification_settings()

    @staticmethod
    async def _ensure_agent_settings(
        connection: aiosqlite.Connection,
        *,
        desktop_sound_enabled: bool,
        desktop_sound_id: str,
    ) -> None:
        await connection.executemany(
            "INSERT OR IGNORE INTO agent_settings(key, value) VALUES (?, ?)",
            (
                ("desktop_sound_enabled", "1" if desktop_sound_enabled else "0"),
                ("desktop_sound_id", desktop_sound_id),
            ),
        )
        await connection.execute(
            "UPDATE agent_settings SET value = ? "
            "WHERE key = 'desktop_sound_id' AND value IN "
            "('signal', 'beacon', 'pulse', 'chime', 'glass', 'rise', 'soft')",
            (DEFAULT_SOUND_ID,),
        )

    async def get_desktop_sound_preferences(self) -> DesktopSoundPreferences:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT key, value FROM agent_settings "
                "WHERE key IN ('desktop_sound_enabled', 'desktop_sound_id')"
            )
            values = {row["key"]: row["value"] for row in await cursor.fetchall()}
        sound_id = values.get("desktop_sound_id", DEFAULT_SOUND_ID)
        if sound_id not in SOUND_VARIANTS:
            sound_id = DEFAULT_SOUND_ID
        return DesktopSoundPreferences(
            enabled=values.get("desktop_sound_enabled", "1") == "1",
            sound_id=sound_id,
        )

    async def update_desktop_sound_preferences(
        self,
        *,
        enabled: bool | None = None,
        sound_id: str | None = None,
    ) -> DesktopSoundPreferences:
        if enabled is None and sound_id is None:
            raise ValueError("At least one desktop sound setting is required")
        if sound_id is not None and sound_id not in SOUND_VARIANTS:
            raise ValueError(f"Unsupported desktop sound id: {sound_id}")
        changes: list[tuple[str, str]] = []
        if enabled is not None:
            changes.append(("desktop_sound_enabled", "1" if enabled else "0"))
        if sound_id is not None:
            changes.append(("desktop_sound_id", sound_id))
        async with self._write_lock, self._connect() as connection:
            await connection.executemany(
                "INSERT INTO agent_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                changes,
            )
            await connection.commit()
        return await self.get_desktop_sound_preferences()

    @staticmethod
    async def _migrate_searches(connection: aiosqlite.Connection) -> None:
        cursor = await connection.execute("PRAGMA table_info(searches)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "default_template_id" not in columns:
            await connection.execute(
                "ALTER TABLE searches ADD COLUMN default_template_id INTEGER "
                "REFERENCES message_templates(id) ON DELETE SET NULL"
            )
        channel_additions = {
            "notify_ntfy": "INTEGER NOT NULL DEFAULT 1",
            "notify_discord": "INTEGER NOT NULL DEFAULT 1",
            "notify_email": "INTEGER NOT NULL DEFAULT 1",
            "notify_desktop_sound": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, definition in channel_additions.items():
            if name not in columns:
                await connection.execute(
                    f"ALTER TABLE searches ADD COLUMN {name} {definition}"  # noqa: S608
                )

    @staticmethod
    async def _migrate_listings(connection: aiosqlite.Connection) -> None:
        """Add M3.1 enrichment fields without replacing an existing M1-M3 database."""

        cursor = await connection.execute("PRAGMA table_info(listings)")
        columns = {row[1] for row in await cursor.fetchall()}
        additions = {
            "article_label": "TEXT NOT NULL DEFAULT 'Artikel'",
            "article_phrase": "TEXT NOT NULL DEFAULT 'der Artikel'",
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
            "SELECT id, title, attributes_json, article_label, article_phrase FROM listings"
        )
        for row in await cursor.fetchall():
            try:
                attributes = json.loads(row["attributes_json"] or "{}")
            except json.JSONDecodeError:
                attributes = {}
            article_label = derive_article_label(row["title"], attributes)
            article_phrase = derive_article_phrase(article_label, row["title"], attributes)
            if row["article_label"] == article_label and row["article_phrase"] == article_phrase:
                continue
            await connection.execute(
                "UPDATE listings SET article_label = ?, article_phrase = ? WHERE id = ?",
                (article_label, article_phrase, row["id"]),
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

    _SEARCH_SELECT = (
        "SELECT searches.*, "
        "(SELECT GROUP_CONCAT(target_id) FROM search_notification_targets "
        " WHERE search_id = searches.id) AS notification_target_ids "
        "FROM searches"
    )

    @staticmethod
    def _parse_target_ids(raw: str | None) -> list[int]:
        if not raw:
            return []
        return [int(value) for value in raw.split(",")]

    @classmethod
    def _row_to_search(cls, row: aiosqlite.Row) -> SearchDefinition:
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
            notification_target_ids=cls._parse_target_ids(row["notification_target_ids"]),
            notify_desktop_sound=bool(row["notify_desktop_sound"]),
            **query_data,
        )

    @staticmethod
    async def _set_search_targets(
        connection: aiosqlite.Connection, search_id: int, target_ids: list[int]
    ) -> None:
        deduped = sorted(set(target_ids))
        await connection.execute(
            "DELETE FROM search_notification_targets WHERE search_id = ?", (search_id,)
        )
        if deduped:
            await connection.executemany(
                "INSERT INTO search_notification_targets(search_id, target_id) VALUES (?, ?)",
                [(search_id, target_id) for target_id in deduped],
            )

    async def create_search(self, data: SearchCreateData) -> SearchDefinition:
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO searches (
                    name, category, query_json, enabled, baseline_initialized,
                    created_at, updated_at, default_template_id, notify_desktop_sound
                ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    data.name,
                    data.category.value,
                    self._query_json(data),
                    int(data.enabled),
                    timestamp,
                    timestamp,
                    data.default_template_id,
                    int(data.notify_desktop_sound),
                ),
            )
            search_id = cursor.lastrowid
            if search_id is None:
                raise RuntimeError("SQLite did not return a search id")
            await self._set_search_targets(connection, search_id, data.notification_target_ids)
            await connection.commit()
        search = await self.get_search(search_id)
        if search is None:
            raise RuntimeError("Created search could not be reloaded")
        return search

    async def get_search(self, search_id: int) -> SearchDefinition | None:
        async with self._connect() as connection:
            cursor = await connection.execute(
                f"{self._SEARCH_SELECT} WHERE searches.id = ?",  # noqa: S608
                (search_id,),
            )
            row = await cursor.fetchone()
        return self._row_to_search(row) if row else None

    async def list_searches(self, *, enabled_only: bool = False) -> list[SearchDefinition]:
        query = self._SEARCH_SELECT
        parameters: tuple[Any, ...] = ()
        if enabled_only:
            query += " WHERE searches.enabled = ?"
            parameters = (1,)
        query += " ORDER BY searches.id"
        async with self._connect() as connection:
            cursor = await connection.execute(query, parameters)  # noqa: S608
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
            "notification_target_ids",
            "notify_desktop_sound",
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
                    baseline_initialized = ?, updated_at = ?, default_template_id = ?,
                    notify_desktop_sound = ?
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
                    int(validated.notify_desktop_sound),
                    search_id,
                ),
            )
            if "notification_target_ids" in changes:
                await self._set_search_targets(
                    connection, search_id, validated.notification_target_ids
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
        desktop_sound_requested = False

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
                                provider_listing_id, title, article_label, article_phrase,
                                price, url, image_url,
                                category, location, seller_name, seller_type, condition,
                                enrichment_status, attributes_json, first_seen_at, last_seen_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(provider_listing_id) DO UPDATE SET
                                title = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.title ELSE excluded.title END,
                                article_label = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.article_label ELSE excluded.article_label END,
                                article_phrase = CASE
                                    WHEN listings.enrichment_status IN ('enriched', 'partial')
                                    THEN listings.article_phrase ELSE excluded.article_phrase END,
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
                                listing.article_phrase,
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
                            if search.notify_desktop_sound:
                                desktop_sound_requested = True

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
            desktop_sound_requested=desktop_sound_requested,
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
                    article_label = ?, article_phrase = ?
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
                    listing.article_phrase,
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
                    listings.article_phrase,
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
                    article_phrase=row["article_phrase"],
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

    async def load_target_dispatch_state(
        self, provider_listing_id: str
    ) -> TargetDispatchState | None:
        """Load the union of notification targets across every matching search, plus
        the already-persisted per-target delivery state for this listing."""

        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT id FROM listings WHERE provider_listing_id = ?",
                (provider_listing_id,),
            )
            listing_row = await cursor.fetchone()
            if listing_row is None:
                return None
            listing_id = listing_row["id"]

            cursor = await connection.execute(
                """
                SELECT DISTINCT search_notification_targets.target_id
                FROM search_matches
                JOIN searches ON searches.id = search_matches.search_id
                JOIN search_notification_targets
                    ON search_notification_targets.search_id = searches.id
                WHERE search_matches.listing_id = ?
                """,
                (listing_id,),
            )
            target_rows = await cursor.fetchall()
            target_ids = {row["target_id"] for row in target_rows}

            cursor = await connection.execute(
                "SELECT target_id, status FROM notification_deliveries WHERE listing_id = ?",
                (listing_id,),
            )
            status_rows = await cursor.fetchall()

        return TargetDispatchState(
            listing_id=listing_id,
            target_ids=target_ids,
            target_statuses={row["target_id"]: row["status"] for row in status_rows},
        )

    async def record_target_delivery_attempt(
        self,
        listing_id: int,
        target_id: int,
        *,
        sent: bool,
        error: str | None = None,
    ) -> None:
        timestamp = to_db_timestamp()
        status = "sent" if sent else "failed"
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO notification_deliveries(
                    listing_id, target_id, status, attempt_count,
                    created_at, updated_at, last_attempt_at, sent_at, last_error
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?)
                ON CONFLICT(listing_id, target_id) DO UPDATE SET
                    status = excluded.status,
                    attempt_count = notification_deliveries.attempt_count + 1,
                    updated_at = excluded.updated_at,
                    last_attempt_at = excluded.last_attempt_at,
                    sent_at = CASE
                        WHEN excluded.status = 'sent' THEN excluded.updated_at
                        ELSE notification_deliveries.sent_at
                    END,
                    last_error = excluded.last_error
                """,
                (
                    listing_id,
                    target_id,
                    status,
                    timestamp,
                    timestamp,
                    timestamp,
                    timestamp if sent else None,
                    None if sent else (error or "")[:1000],
                ),
            )
            await connection.commit()

    async def record_target_delivery_skipped(self, listing_id: int, target_id: int) -> None:
        """Persist that one target was not attempted, without touching a 'sent' outcome."""

        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                INSERT INTO notification_deliveries(
                    listing_id, target_id, status, attempt_count, created_at, updated_at
                ) VALUES (?, ?, 'skipped', 0, ?, ?)
                ON CONFLICT(listing_id, target_id) DO UPDATE SET
                    status = CASE
                        WHEN notification_deliveries.status = 'sent'
                        THEN notification_deliveries.status
                        ELSE 'skipped'
                    END,
                    updated_at = excluded.updated_at
                """,
                (listing_id, target_id, timestamp, timestamp),
            )
            await connection.commit()

    # -- Notification targets (reusable ntfy/Discord/e-mail destinations) --------------

    @staticmethod
    def _row_to_target(row: aiosqlite.Row) -> NotificationTargetRecord:
        return NotificationTargetRecord(
            id=row["id"],
            type=row["type"],
            name=row["name"],
            enabled=bool(row["enabled"]),
            ntfy_base_url=row["ntfy_base_url"],
            email_address=row["email_address"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def create_notification_target(
        self,
        *,
        type: str,  # noqa: A002
        name: str,
        enabled: bool = True,
        ntfy_base_url: str | None = None,
        email_address: str | None = None,
    ) -> NotificationTargetRecord:
        if type not in NOTIFICATION_TARGET_TYPES:
            raise ValueError(f"Unsupported notification target type: {type}")
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                """
                INSERT INTO notification_targets(
                    type, name, enabled, ntfy_base_url, email_address, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    type,
                    name,
                    int(enabled),
                    ntfy_base_url,
                    email_address,
                    timestamp,
                    timestamp,
                ),
            )
            target_id = cursor.lastrowid
            await connection.commit()
        if target_id is None:
            raise RuntimeError("SQLite did not return a notification target id")
        target = await self.get_notification_target(target_id)
        if target is None:
            raise RuntimeError("Created notification target could not be reloaded")
        return target

    async def get_notification_target(self, target_id: int) -> NotificationTargetRecord | None:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT * FROM notification_targets WHERE id = ?", (target_id,)
            )
            row = await cursor.fetchone()
        return self._row_to_target(row) if row else None

    async def list_notification_targets(
        self,
        *,
        type: str | None = None,  # noqa: A002
    ) -> list[NotificationTargetRecord]:
        query = "SELECT * FROM notification_targets"
        parameters: tuple[Any, ...] = ()
        if type is not None:
            query += " WHERE type = ?"
            parameters = (type,)
        query += " ORDER BY type, name, id"
        async with self._connect() as connection:
            cursor = await connection.execute(query, parameters)  # noqa: S608
            rows = await cursor.fetchall()
        return [self._row_to_target(row) for row in rows]

    async def update_notification_target(
        self, target_id: int, changes: dict[str, Any]
    ) -> NotificationTargetRecord | None:
        current = await self.get_notification_target(target_id)
        if current is None:
            return None
        allowed = {"name", "enabled", "ntfy_base_url", "email_address"}
        if not set(changes) <= allowed:
            raise ValueError("Unsupported notification target field")
        name = changes.get("name", current.name)
        enabled = changes.get("enabled", current.enabled)
        ntfy_base_url = changes.get("ntfy_base_url", current.ntfy_base_url)
        email_address = changes.get("email_address", current.email_address)
        timestamp = to_db_timestamp()
        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                """
                UPDATE notification_targets
                SET name = ?, enabled = ?, ntfy_base_url = ?, email_address = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, int(enabled), ntfy_base_url, email_address, timestamp, target_id),
            )
            await connection.commit()
        return await self.get_notification_target(target_id)

    async def delete_notification_target(self, target_id: int) -> bool:
        async with self._write_lock, self._connect() as connection:
            cursor = await connection.execute(
                "DELETE FROM notification_targets WHERE id = ?", (target_id,)
            )
            await connection.commit()
        return cursor.rowcount > 0

    async def count_searches_using_target(self, target_id: int) -> int:
        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT COUNT(DISTINCT search_id) FROM search_notification_targets "
                "WHERE target_id = ?",
                (target_id,),
            )
            row = await cursor.fetchone()
        return int(row[0])

    # -- One-time migration helpers (M5/M6 -> notification targets) --------------------

    async def seed_legacy_agent_settings(self, raw: dict[str, str]) -> None:
        """One-time env-var bootstrap for the pre-target legacy config keys.

        Only ever consumed by the migration in
        agent/app/notifications/target_migration.py on a brand-new install where the
        user already had NTFY_*/DISCORD_*/EMAIL_* variables in .env — it lets those
        still create the equivalent default targets on first startup.
        """

        if not raw:
            return
        async with self._write_lock, self._connect() as connection:
            await connection.executemany(
                "INSERT OR IGNORE INTO agent_settings(key, value) VALUES (?, ?)",
                list(raw.items()),
            )
            await connection.commit()

    async def get_legacy_notification_config(self) -> dict[str, str]:
        """Read pre-target global settings rows still sitting in agent_settings, if any.

        Only ever used by the one-time migration in
        agent/app/notifications/target_migration.py; the live application no longer
        reads or writes these keys.
        """

        legacy_keys = (
            "ntfy_enabled",
            "ntfy_base_url",
            "ntfy_topic",
            "discord_enabled",
            "email_enabled",
            "email_to_address",
        )
        placeholders = ",".join("?" for _ in legacy_keys)
        async with self._connect() as connection:
            cursor = await connection.execute(
                f"SELECT key, value FROM agent_settings WHERE key IN ({placeholders})",  # noqa: S608
                legacy_keys,
            )
            rows = await cursor.fetchall()
        return {row["key"]: row["value"] for row in rows}

    async def list_search_legacy_channel_flags(self) -> list[tuple[int, bool, bool, bool]]:
        """Read the pre-target per-search notify_ntfy/discord/email booleans directly.

        Only used by the one-time migration; the live application derives per-search
        delivery targets from search_notification_targets instead.
        """

        async with self._connect() as connection:
            cursor = await connection.execute(
                "SELECT id, notify_ntfy, notify_discord, notify_email FROM searches"
            )
            rows = await cursor.fetchall()
        return [
            (
                row["id"],
                bool(row["notify_ntfy"]),
                bool(row["notify_discord"]),
                bool(row["notify_email"]),
            )
            for row in rows
        ]

    async def link_search_to_target(self, search_id: int, target_id: int) -> None:
        """Add one target to a search's notification targets without touching the rest.

        Used by the one-time legacy migration; normal writes go through update_search.
        """

        async with self._write_lock, self._connect() as connection:
            await connection.execute(
                "INSERT OR IGNORE INTO search_notification_targets(search_id, target_id) "
                "VALUES (?, ?)",
                (search_id, target_id),
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
                        article_phrase=row["article_phrase"],
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
            article_phrase=row["article_phrase"],
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
