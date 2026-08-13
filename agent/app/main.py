from __future__ import annotations

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
from agent.app.notifications.service import FakeNotificationService, NotificationService
from agent.app.storage.database import Database
from agent.app.willhaben.marketplace_provider import WillhabenMarketplaceProvider


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
    resolved_notifications = notification_service or FakeNotificationService()
    database = Database(resolved_settings.database_path)
    health = HealthState()
    scheduler = Scheduler(
        database=database,
        provider=resolved_provider,
        notification_service=resolved_notifications,
        health=health,
        cycle_interval_seconds=resolved_settings.cycle_interval_seconds,
        max_concurrent_requests=resolved_settings.max_concurrent_requests,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        await database.initialize()
        if resolved_settings.scheduler_enabled:
            scheduler.start()
        yield
        await scheduler.stop()

    app = FastAPI(
        title="Willhaben-Suchagent",
        version="0.2.0",
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
