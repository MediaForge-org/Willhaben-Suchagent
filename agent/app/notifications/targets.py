"""Owns one live, independently configured NotificationService per notification target.

A "target" is a reusable, named destination (one ntfy topic, one Discord webhook, one
e-mail recipient). Searches reference targets by id instead of toggling a single global
channel, so the same Discord webhook or ntfy topic can be reused across many searches
while each target still gets its own on/off switch, its own secrets, and its own test
button — see agent/app/storage/database.py:NotificationTargetRecord for the persisted
shape and agent/app/notifications/dispatcher.py for how deliveries are deduplicated
across every search that references the same target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.app.core.secret_store import SecretStore
from agent.app.notifications.service import (
    DiscordNotificationService,
    EmailNotificationService,
    NotificationService,
    NtfyNotificationService,
)
from agent.app.storage.database import Database, NotificationTargetRecord


class NotificationTargetNotFoundError(LookupError):
    """No notification target exists for the given id."""


def ntfy_secret_keys(target_id: int) -> tuple[str, str]:
    return f"ntfy_target_{target_id}_topic", f"ntfy_target_{target_id}_token"


def discord_secret_key(target_id: int) -> str:
    return f"discord_target_{target_id}_webhook_url"


class NotificationTargetRegistry:
    def __init__(self, *, database: Database, secret_store: SecretStore) -> None:
        self._database = database
        self._secrets = secret_store
        self._services: dict[int, NotificationService] = {}

    def get(self, target_id: int) -> NotificationService | None:
        return self._services.get(target_id)

    def all_services(self) -> list[NotificationService]:
        return list(self._services.values())

    async def reload_all(self) -> None:
        targets = await self._database.list_notification_targets()
        settings = await self._database.get_notification_settings()
        secrets = self._secrets.load()
        live_ids = set()
        for target in targets:
            live_ids.add(target.id)
            self._configure_target(target, settings, secrets)
        stale_ids = set(self._services) - live_ids
        for target_id in stale_ids:
            service = self._services.pop(target_id)
            await service.close()

    async def reload_one(self, target_id: int) -> None:
        target = await self._database.get_notification_target(target_id)
        if target is None:
            service = self._services.pop(target_id, None)
            if service is not None:
                await service.close()
            return
        settings = await self._database.get_notification_settings()
        secrets = self._secrets.load()
        self._configure_target(target, settings, secrets)

    def _configure_target(
        self, target: NotificationTargetRecord, settings: object, secrets: dict[str, str]
    ) -> None:
        if target.type == "ntfy":
            topic_key, token_key = ntfy_secret_keys(target.id)
            service = self._services.get(target.id)
            if not isinstance(service, NtfyNotificationService):
                service = NtfyNotificationService(enabled=False, base_url="", topic=None)
                self._services[target.id] = service
            service.configure(
                enabled=target.enabled,
                base_url=target.ntfy_base_url or "https://ntfy.sh",
                topic=secrets.get(topic_key) or None,
                token=secrets.get(token_key) or None,
                timeout_seconds=settings.ntfy_timeout_seconds,  # type: ignore[attr-defined]
            )
        elif target.type == "discord":
            webhook_key = discord_secret_key(target.id)
            service = self._services.get(target.id)
            if not isinstance(service, DiscordNotificationService):
                service = DiscordNotificationService(enabled=False, webhook_url=None)
                self._services[target.id] = service
            service.configure(
                enabled=target.enabled,
                webhook_url=secrets.get(webhook_key) or None,
                timeout_seconds=settings.discord_timeout_seconds,  # type: ignore[attr-defined]
            )
        elif target.type == "email":
            service = self._services.get(target.id)
            if not isinstance(service, EmailNotificationService):
                service = EmailNotificationService(
                    enabled=False, smtp_host=None, from_address=None, to_address=None
                )
                self._services[target.id] = service
            service.configure(
                enabled=target.enabled,
                smtp_host=settings.email_smtp_host,  # type: ignore[attr-defined]
                smtp_port=settings.email_smtp_port,  # type: ignore[attr-defined]
                username=settings.email_smtp_username,  # type: ignore[attr-defined]
                password=secrets.get("email_smtp_password") or None,
                from_address=settings.email_from_address,  # type: ignore[attr-defined]
                to_address=target.email_address,
                encryption=settings.email_encryption,  # type: ignore[attr-defined, arg-type]
                timeout_seconds=settings.email_timeout_seconds,  # type: ignore[attr-defined]
            )

    async def close(self) -> None:
        for service in self._services.values():
            await service.close()
        self._services.clear()


def mask_email_address(address: str) -> str:
    local, _, domain = address.partition("@")
    if not domain or not local:
        return "•••"
    return f"{local[0]}***@{domain}"


@dataclass(frozen=True, slots=True)
class NotificationTargetSnapshot:
    id: int
    type: str
    name: str
    enabled: bool
    configured: bool
    ntfy_base_url: str | None
    ntfy_topic_configured: bool
    ntfy_token_configured: bool
    discord_webhook_configured: bool
    email_address: str | None
    email_address_masked: str | None
    created_at: str
    updated_at: str


class NotificationTargetService:
    """CRUD for notification targets, keeping secrets out of every response."""

    def __init__(
        self,
        *,
        database: Database,
        secret_store: SecretStore,
        registry: NotificationTargetRegistry,
    ) -> None:
        self._database = database
        self._secrets = secret_store
        self._registry = registry

    async def _snapshot(self, target: NotificationTargetRecord) -> NotificationTargetSnapshot:
        secrets = self._secrets.load()
        service = self._registry.get(target.id)
        configured = service.configured if service is not None else False
        topic_key, token_key = ntfy_secret_keys(target.id)
        return NotificationTargetSnapshot(
            id=target.id,
            type=target.type,
            name=target.name,
            enabled=target.enabled,
            configured=configured,
            ntfy_base_url=target.ntfy_base_url,
            ntfy_topic_configured=bool(secrets.get(topic_key)),
            ntfy_token_configured=bool(secrets.get(token_key)),
            discord_webhook_configured=bool(secrets.get(discord_secret_key(target.id))),
            email_address=target.email_address,
            email_address_masked=(
                mask_email_address(target.email_address) if target.email_address else None
            ),
            created_at=target.created_at.isoformat(),
            updated_at=target.updated_at.isoformat(),
        )

    async def list(self, *, type: str | None = None) -> list[NotificationTargetSnapshot]:  # noqa: A002
        targets = await self._database.list_notification_targets(type=type)
        return [await self._snapshot(target) for target in targets]

    async def get(self, target_id: int) -> NotificationTargetSnapshot:
        target = await self._database.get_notification_target(target_id)
        if target is None:
            raise NotificationTargetNotFoundError(target_id)
        return await self._snapshot(target)

    async def create(self, payload: dict[str, Any]) -> NotificationTargetSnapshot:
        target_type = payload["type"]
        name = payload["name"]
        if target_type == "discord" and payload.get("webhook_url"):
            DiscordNotificationService.validate_webhook_url(payload["webhook_url"])
        target = await self._database.create_notification_target(
            type=target_type,
            name=name,
            enabled=payload.get("enabled", True),
            ntfy_base_url=payload.get("base_url") if target_type == "ntfy" else None,
            email_address=payload.get("email_address") if target_type == "email" else None,
        )
        await self._apply_secrets(target.id, target_type, payload)
        await self._registry.reload_one(target.id)
        return await self.get(target.id)

    async def update(self, target_id: int, payload: dict[str, Any]) -> NotificationTargetSnapshot:
        target = await self._database.get_notification_target(target_id)
        if target is None:
            raise NotificationTargetNotFoundError(target_id)
        if target.type == "discord" and payload.get("webhook_url"):
            DiscordNotificationService.validate_webhook_url(payload["webhook_url"])
        db_changes: dict[str, Any] = {}
        if "name" in payload:
            db_changes["name"] = payload["name"]
        if "enabled" in payload:
            db_changes["enabled"] = payload["enabled"]
        if target.type == "ntfy" and "base_url" in payload:
            db_changes["ntfy_base_url"] = payload["base_url"]
        if target.type == "email" and "email_address" in payload:
            db_changes["email_address"] = payload["email_address"]
        if db_changes:
            await self._database.update_notification_target(target_id, db_changes)
        await self._apply_secrets(target_id, target.type, payload)
        await self._registry.reload_one(target_id)
        return await self.get(target_id)

    async def _apply_secrets(
        self, target_id: int, target_type: str, payload: dict[str, Any]
    ) -> None:
        if target_type == "ntfy":
            topic_key, token_key = ntfy_secret_keys(target_id)
            secrets_to_set: dict[str, str | None] = {}
            if payload.get("topic"):
                secrets_to_set[topic_key] = payload["topic"]
            if payload.get("token"):
                secrets_to_set[token_key] = payload["token"]
            if secrets_to_set:
                self._secrets.set_many(secrets_to_set)
        elif target_type == "discord" and payload.get("webhook_url"):
            self._secrets.set_many({discord_secret_key(target_id): payload["webhook_url"]})

    async def delete(self, target_id: int) -> int:
        """Delete the target and return how many searches had referenced it."""

        target = await self._database.get_notification_target(target_id)
        if target is None:
            raise NotificationTargetNotFoundError(target_id)
        usage_count = await self._database.count_searches_using_target(target_id)
        await self._database.delete_notification_target(target_id)
        secret_keys: list[str] = []
        if target.type == "ntfy":
            secret_keys.extend(ntfy_secret_keys(target_id))
        elif target.type == "discord":
            secret_keys.append(discord_secret_key(target_id))
        if secret_keys:
            self._secrets.set_many(dict.fromkeys(secret_keys, None))
        await self._registry.reload_one(target_id)
        return usage_count

    async def usage_count(self, target_id: int) -> int:
        return await self._database.count_searches_using_target(target_id)
