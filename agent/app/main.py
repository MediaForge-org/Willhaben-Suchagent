from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from agent.app._version import __version__
from agent.app.api.routes import router
from agent.app.core.config import Settings
from agent.app.core.health import HealthState
from agent.app.core.instance_lock import already_running_message, is_port_available
from agent.app.core.logging import configure_logging
from agent.app.core.provider import ListingProvider
from agent.app.core.scheduler import Scheduler
from agent.app.core.secret_store import SecretStore
from agent.app.notifications.dispatcher import NotificationDispatcher
from agent.app.notifications.service import NotificationService
from agent.app.notifications.settings_manager import NotificationSettingsManager
from agent.app.notifications.sound import (
    DesktopNotificationSoundService,
    create_desktop_sound_service,
)
from agent.app.notifications.target_migration import migrate_legacy_notification_settings
from agent.app.notifications.targets import NotificationTargetRegistry, NotificationTargetService
from agent.app.storage.database import Database, NotificationSettingsRecord
from agent.app.willhaben.marketplace_detail_client import WillhabenMarketplaceDetailClient
from agent.app.willhaben.marketplace_listing_enricher import (
    WillhabenMarketplaceListingEnricher,
)
from agent.app.willhaben.marketplace_provider import WillhabenMarketplaceProvider

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    provider: ListingProvider | None = None,
    notification_service: NotificationService | None = None,
    desktop_sound_service: DesktopNotificationSoundService | None = None,
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_provider = provider or WillhabenMarketplaceProvider(
        user_agent=resolved_settings.marketplace_user_agent,
        connect_timeout_seconds=resolved_settings.marketplace_connect_timeout_seconds,
        read_timeout_seconds=resolved_settings.marketplace_read_timeout_seconds,
        max_redirects=resolved_settings.marketplace_max_redirects,
        max_response_bytes=resolved_settings.marketplace_max_response_bytes,
    )
    database = Database(resolved_settings.database_path)
    secret_store_path = resolved_settings.secret_store_path or (
        resolved_settings.database_path.parent / "secrets.json"
    )
    secret_store = SecretStore(secret_store_path)

    # Global, provider-technical settings only (SMTP sender account + per-channel
    # timeouts) — per-destination config now lives in notification targets, migrated
    # from these same .env values on first startup (see target_migration.py).
    env_notification_settings_seed = NotificationSettingsRecord(
        ntfy_timeout_seconds=resolved_settings.ntfy_timeout_seconds,
        discord_timeout_seconds=resolved_settings.discord_timeout_seconds,
        email_smtp_host=resolved_settings.email_smtp_host,
        email_smtp_port=resolved_settings.email_smtp_port,
        email_smtp_username=resolved_settings.email_smtp_username,
        email_from_address=resolved_settings.email_from_address,
        email_encryption="starttls" if resolved_settings.email_use_tls else "none",
        email_timeout_seconds=resolved_settings.email_timeout_seconds,
    )
    env_secret_seed = {
        "ntfy_token": (
            resolved_settings.ntfy_token.get_secret_value()
            if resolved_settings.ntfy_token is not None
            else None
        ),
        "discord_webhook_url": resolved_settings.discord_webhook_url,
        "email_smtp_password": (
            resolved_settings.email_smtp_password.get_secret_value()
            if resolved_settings.email_smtp_password is not None
            else None
        ),
    }
    env_legacy_config_seed = {
        "ntfy_enabled": "1" if resolved_settings.ntfy_enabled else "0",
        "ntfy_base_url": resolved_settings.ntfy_base_url,
        "ntfy_topic": resolved_settings.ntfy_topic or "",
        "discord_enabled": "1" if resolved_settings.discord_enabled else "0",
        "email_enabled": "1" if resolved_settings.email_enabled else "0",
        "email_to_address": resolved_settings.email_to_address or "",
    }

    target_registry = NotificationTargetRegistry(database=database, secret_store=secret_store)
    notification_settings_manager: NotificationSettingsManager | None = None
    target_service: NotificationTargetService | None = None
    if notification_service is None:
        notification_settings_manager = NotificationSettingsManager(
            database=database,
            secret_store=secret_store,
            targets=target_registry,
        )
        target_service = NotificationTargetService(
            database=database,
            secret_store=secret_store,
            registry=target_registry,
        )
    resolved_notifications = notification_service or NotificationDispatcher(
        database=database,
        targets=target_registry,
    )
    resolved_desktop_sound = desktop_sound_service or create_desktop_sound_service(
        enabled=resolved_settings.desktop_sound_enabled,
        sound_id=resolved_settings.desktop_sound_id,
    )
    health = HealthState()
    listing_enricher = None
    if provider is None:
        listing_enricher = WillhabenMarketplaceListingEnricher(
            WillhabenMarketplaceDetailClient(
                user_agent=resolved_settings.marketplace_user_agent,
                connect_timeout_seconds=resolved_settings.marketplace_connect_timeout_seconds,
                read_timeout_seconds=resolved_settings.marketplace_read_timeout_seconds,
                max_redirects=resolved_settings.marketplace_max_redirects,
                max_response_bytes=resolved_settings.marketplace_max_response_bytes,
            )
        )
    scheduler = Scheduler(
        database=database,
        provider=resolved_provider,
        notification_service=resolved_notifications,
        health=health,
        cycle_interval_seconds=resolved_settings.cycle_interval_seconds,
        max_concurrent_requests=resolved_settings.max_concurrent_requests,
        listing_enricher=listing_enricher,
        desktop_sound_service=resolved_desktop_sound,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        secret_store.seed_defaults(env_secret_seed)
        await database.initialize(
            desktop_sound_enabled=resolved_settings.desktop_sound_enabled,
            desktop_sound_id=resolved_settings.desktop_sound_id,
            notification_settings_seed=env_notification_settings_seed,
        )
        if notification_settings_manager is not None:
            await database.seed_legacy_agent_settings(env_legacy_config_seed)
            await migrate_legacy_notification_settings(database, secret_store)
            await notification_settings_manager.reload_from_storage()
        desktop_sound_preferences = await database.get_desktop_sound_preferences()
        resolved_desktop_sound.configure(
            enabled=desktop_sound_preferences.enabled,
            sound_id=desktop_sound_preferences.sound_id,
        )
        if not resolved_notifications.enabled:
            logger.info(
                "notification_service_disabled reason=%s",
                resolved_notifications.disabled_reason,
            )
        if not resolved_desktop_sound.enabled:
            logger.info("desktop_sound_disabled reason=%s", resolved_desktop_sound.disabled_reason)
        elif not resolved_desktop_sound.available:
            logger.warning(
                "desktop_sound_unavailable reason=%s",
                resolved_desktop_sound.disabled_reason,
            )
        if resolved_settings.scheduler_enabled:
            scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            await resolved_notifications.close()

    app = FastAPI(
        title="Willhaben-Suchagent",
        version=__version__,
        description="Local API for the Willhaben live search agent",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.health = health
    app.state.scheduler = scheduler
    app.state.provider = resolved_provider
    app.state.notification_service = resolved_notifications
    app.state.notification_target_registry = target_registry
    app.state.notification_target_service = target_service
    app.state.notification_settings_manager = notification_settings_manager
    app.state.secret_store = secret_store
    app.state.desktop_sound_service = resolved_desktop_sound
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    settings = Settings()
    if not is_port_available(settings.api_host, settings.api_port):
        print(already_running_message(settings.api_host, settings.api_port))  # noqa: T201
        return
    uvicorn.run(
        "agent.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
