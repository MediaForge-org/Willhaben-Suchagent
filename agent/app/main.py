from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from agent.app.api.routes import router
from agent.app.core.config import Settings
from agent.app.core.health import HealthState
from agent.app.core.logging import configure_logging
from agent.app.core.provider import ListingProvider
from agent.app.core.scheduler import Scheduler
from agent.app.notifications.service import NotificationService, NtfyNotificationService
from agent.app.storage.database import Database
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
) -> FastAPI:
    resolved_settings = settings or Settings()
    resolved_provider = provider or WillhabenMarketplaceProvider(
        user_agent=resolved_settings.marketplace_user_agent,
        connect_timeout_seconds=resolved_settings.marketplace_connect_timeout_seconds,
        read_timeout_seconds=resolved_settings.marketplace_read_timeout_seconds,
        max_redirects=resolved_settings.marketplace_max_redirects,
        max_response_bytes=resolved_settings.marketplace_max_response_bytes,
    )
    resolved_notifications = notification_service or NtfyNotificationService(
        enabled=resolved_settings.ntfy_enabled,
        base_url=resolved_settings.ntfy_base_url,
        topic=resolved_settings.ntfy_topic,
        token=(
            resolved_settings.ntfy_token.get_secret_value()
            if resolved_settings.ntfy_token is not None
            else None
        ),
        timeout_seconds=resolved_settings.ntfy_timeout_seconds,
    )
    database = Database(resolved_settings.database_path)
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
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        await database.initialize()
        if not resolved_notifications.enabled:
            logger.info(
                "notification_service_disabled reason=%s",
                resolved_notifications.disabled_reason,
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
        version="0.3.1",
        description="Local API for the Willhaben live search agent",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.database = database
    app.state.health = health
    app.state.scheduler = scheduler
    app.state.provider = resolved_provider
    app.state.notification_service = resolved_notifications
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    settings = Settings()
    uvicorn.run(
        "agent.app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
