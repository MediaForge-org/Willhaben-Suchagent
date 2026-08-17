"""One-time migration from the M5/M6 single global ntfy/Discord/e-mail config to the
M7-preparatory reusable notification-targets model.

Runs once at startup, after ``Database.initialize()`` and before the target registry
loads live channel instances. It is a pure additive metadata migration: it only ever
inserts rows into ``notification_targets`` / ``search_notification_targets`` and moves
secrets to their new per-target keys. It never touches listings, search_matches,
baselines, or the notifications/delivery history — so it can never trigger a
notification and can never reset a baseline.

Idempotent: it does nothing once at least one notification target already exists,
so a second startup (or a startup against an already-migrated database) is a no-op.
"""

from __future__ import annotations

import logging

from agent.app.core.secret_store import SecretStore
from agent.app.storage.database import Database

logger = logging.getLogger(__name__)

DEFAULT_NTFY_TARGET_NAME = "Standard Push"
DEFAULT_DISCORD_TARGET_NAME = "Standard Discord"
DEFAULT_EMAIL_TARGET_NAME = "Standard E-Mail"


async def migrate_legacy_notification_settings(
    database: Database, secret_store: SecretStore
) -> None:
    existing = await database.list_notification_targets()
    if existing:
        return

    legacy = await database.get_legacy_notification_config()
    secrets = secret_store.load()

    ntfy_target_id: int | None = None
    if legacy.get("ntfy_enabled") == "1" and legacy.get("ntfy_topic"):
        target = await database.create_notification_target(
            type="ntfy",
            name=DEFAULT_NTFY_TARGET_NAME,
            enabled=True,
            ntfy_base_url=legacy.get("ntfy_base_url") or "https://ntfy.sh",
        )
        ntfy_target_id = target.id
        target_secrets = {f"ntfy_target_{target.id}_topic": legacy["ntfy_topic"]}
        if secrets.get("ntfy_token"):
            target_secrets[f"ntfy_target_{target.id}_token"] = secrets["ntfy_token"]
        secret_store.set_many(target_secrets)
        logger.info("migrated_legacy_ntfy_target target_id=%s", target.id)

    discord_target_id: int | None = None
    if legacy.get("discord_enabled") == "1" and secrets.get("discord_webhook_url"):
        target = await database.create_notification_target(
            type="discord",
            name=DEFAULT_DISCORD_TARGET_NAME,
            enabled=True,
        )
        discord_target_id = target.id
        secret_store.set_many(
            {f"discord_target_{target.id}_webhook_url": secrets["discord_webhook_url"]}
        )
        logger.info("migrated_legacy_discord_target target_id=%s", target.id)

    email_target_id: int | None = None
    if legacy.get("email_enabled") == "1" and legacy.get("email_to_address"):
        target = await database.create_notification_target(
            type="email",
            name=DEFAULT_EMAIL_TARGET_NAME,
            enabled=True,
            email_address=legacy["email_to_address"],
        )
        email_target_id = target.id
        logger.info("migrated_legacy_email_target target_id=%s", target.id)

    if not (ntfy_target_id or discord_target_id or email_target_id):
        return

    for (
        search_id,
        notify_ntfy,
        notify_discord,
        notify_email,
    ) in await database.list_search_legacy_channel_flags():
        if notify_ntfy and ntfy_target_id is not None:
            await database.link_search_to_target(search_id, ntfy_target_id)
        if notify_discord and discord_target_id is not None:
            await database.link_search_to_target(search_id, discord_target_id)
        if notify_email and email_target_id is not None:
            await database.link_search_to_target(search_id, email_target_id)
