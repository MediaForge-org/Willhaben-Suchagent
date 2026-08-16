from __future__ import annotations

import asyncio
import logging

from agent.app.core.models import Listing
from agent.app.notifications.service import NotificationDeliveryError, NotificationService
from agent.app.storage.database import PUSH_CHANNELS, Database

logger = logging.getLogger(__name__)


class NotificationDispatcher(NotificationService):
    """Fan one new-listing notification out to independently toggled channels.

    Each channel's delivery outcome is persisted per listing before the next channel
    runs, so a channel outage never blocks the others and a retried cycle never
    re-delivers a channel that already succeeded.
    """

    def __init__(self, *, database: Database, channels: dict[str, NotificationService]) -> None:
        self.database = database
        self.channels = channels

    @property
    def enabled(self) -> bool:
        return any(service.enabled for service in self.channels.values())

    @property
    def disabled_reason(self) -> str | None:
        if self.enabled:
            return None
        reasons = [
            f"{name}: {service.disabled_reason}"
            for name, service in self.channels.items()
            if service.disabled_reason
        ]
        return "; ".join(reasons) or "No notification channel is configured"

    async def notify_new_listing(self, listing: Listing) -> None:
        state = await self.database.load_channel_dispatch_state(listing.provider_listing_id)
        if state is None:
            logger.warning(
                "dispatch_skipped_unknown_listing provider_listing_id=%s",
                listing.provider_listing_id,
            )
            return

        errors: dict[str, str] = {}
        for channel_name in PUSH_CHANNELS:
            if state.channel_statuses.get(channel_name) == "sent":
                continue
            service = self.channels.get(channel_name)
            if channel_name not in state.enabled_channels or service is None or not service.enabled:
                await self.database.record_channel_delivery_skipped(state.listing_id, channel_name)
                continue
            try:
                await service.notify_new_listing(listing)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                errors[channel_name] = f"{type(error).__name__}: {error}"
                await self.database.record_channel_delivery_attempt(
                    state.listing_id,
                    channel_name,
                    sent=False,
                    error=str(error),
                )
                logger.error(
                    "channel_delivery_failed channel=%s provider_listing_id=%s error_type=%s",
                    channel_name,
                    listing.provider_listing_id,
                    type(error).__name__,
                )
                continue
            await self.database.record_channel_delivery_attempt(
                state.listing_id, channel_name, sent=True
            )
            logger.info(
                "channel_delivery_sent channel=%s provider_listing_id=%s",
                channel_name,
                listing.provider_listing_id,
            )

        if errors:
            raise NotificationDeliveryError(
                "; ".join(f"{channel}: {message}" for channel, message in errors.items())
            )

    async def notify_test(self) -> None:
        errors: dict[str, str] = {}
        for channel_name, service in self.channels.items():
            if not service.enabled:
                continue
            try:
                await service.notify_test()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                errors[channel_name] = f"{type(error).__name__}: {error}"
        if errors:
            raise NotificationDeliveryError(
                "; ".join(f"{channel}: {message}" for channel, message in errors.items())
            )

    async def close(self) -> None:
        for service in self.channels.values():
            await service.close()
