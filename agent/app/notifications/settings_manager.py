"""Coordinates the remaining GLOBAL notification settings: the shared SMTP sender
account and the per-channel-type request timeouts.

Per-destination configuration (which ntfy topic, which Discord webhook, which e-mail
recipient) lives in notification targets instead — see agent/app/notifications/targets.py.
A settings save here still reconfigures every already-running target's live channel
instance in place (via the registry), so it takes effect immediately, no restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.app.core.secret_store import SecretStore
from agent.app.notifications.targets import NotificationTargetRegistry
from agent.app.storage.database import Database


def mask_email_address(address: str) -> str:
    local, _, domain = address.partition("@")
    if not domain or not local:
        return "•••"
    return f"{local[0]}***@{domain}"


@dataclass(frozen=True, slots=True)
class GlobalNotificationSettingsSnapshot:
    ntfy_timeout_seconds: float
    discord_timeout_seconds: float
    email_smtp_host: str | None
    email_smtp_port: int
    email_smtp_username: str | None
    email_smtp_password_configured: bool
    email_from_address: str | None
    email_encryption: str
    email_timeout_seconds: float


class NotificationSettingsManager:
    def __init__(
        self,
        *,
        database: Database,
        secret_store: SecretStore,
        targets: NotificationTargetRegistry,
    ) -> None:
        self._database = database
        self._secrets = secret_store
        self.targets = targets

    async def reload_from_storage(self) -> None:
        await self.targets.reload_all()

    async def snapshot(self) -> GlobalNotificationSettingsSnapshot:
        settings = await self._database.get_notification_settings()
        secrets = self._secrets.load()
        return GlobalNotificationSettingsSnapshot(
            ntfy_timeout_seconds=settings.ntfy_timeout_seconds,
            discord_timeout_seconds=settings.discord_timeout_seconds,
            email_smtp_host=settings.email_smtp_host,
            email_smtp_port=settings.email_smtp_port,
            email_smtp_username=settings.email_smtp_username,
            email_smtp_password_configured=bool(secrets.get("email_smtp_password")),
            email_from_address=settings.email_from_address,
            email_encryption=settings.email_encryption,
            email_timeout_seconds=settings.email_timeout_seconds,
        )

    async def update_global(self, changes: dict[str, Any]) -> None:
        db_changes: dict[str, Any] = {}
        if "ntfy_timeout_seconds" in changes:
            db_changes["ntfy_timeout_seconds"] = float(changes["ntfy_timeout_seconds"])
        if "discord_timeout_seconds" in changes:
            db_changes["discord_timeout_seconds"] = float(changes["discord_timeout_seconds"])
        if "email_smtp_host" in changes:
            db_changes["email_smtp_host"] = changes["email_smtp_host"]
        if "email_smtp_port" in changes:
            db_changes["email_smtp_port"] = int(changes["email_smtp_port"])
        if "email_smtp_username" in changes:
            db_changes["email_smtp_username"] = changes["email_smtp_username"]
        if "email_from_address" in changes:
            db_changes["email_from_address"] = changes["email_from_address"]
        if "email_encryption" in changes:
            db_changes["email_encryption"] = changes["email_encryption"]
        if "email_timeout_seconds" in changes:
            db_changes["email_timeout_seconds"] = float(changes["email_timeout_seconds"])
        if db_changes:
            await self._database.update_notification_settings(db_changes)
        if changes.get("email_smtp_password"):
            self._secrets.set_many({"email_smtp_password": str(changes["email_smtp_password"])})
        await self.reload_from_storage()
