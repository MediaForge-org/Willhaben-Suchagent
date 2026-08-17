from __future__ import annotations

import asyncio
import logging

from agent.app.core.models import Listing
from agent.app.notifications.service import NotificationDeliveryError, NotificationService
from agent.app.notifications.targets import NotificationTargetRegistry
from agent.app.storage.database import Database

logger = logging.getLogger(__name__)


class NotificationDispatcher(NotificationService):
    """Fan one new-listing notification out to every notification target referenced by
    any search that matched this listing.

    Delivery identity is per *target*, not per channel type: two searches that both
    reference the same Discord webhook target only ever deliver to it once, while two
    searches referencing two different targets of the same type (e.g. two separate
    ntfy topics) each get their own independent delivery. Each target's outcome is
    persisted before the next target runs, so one target's outage never blocks the
    others and a retried cycle never re-delivers a target that already succeeded.
    """

    def __init__(self, *, database: Database, targets: NotificationTargetRegistry) -> None:
        self.database = database
        self.targets = targets

    @property
    def enabled(self) -> bool:
        return any(service.enabled for service in self.targets.all_services())

    @property
    def disabled_reason(self) -> str | None:
        if self.enabled:
            return None
        return "No notification target is configured and enabled"

    async def notify_new_listing(self, listing: Listing) -> None:
        state = await self.database.load_target_dispatch_state(listing.provider_listing_id)
        if state is None:
            logger.warning(
                "dispatch_skipped_unknown_listing provider_listing_id=%s",
                listing.provider_listing_id,
            )
            return

        errors: dict[int, str] = {}
        for target_id in sorted(state.target_ids):
            if state.target_statuses.get(target_id) == "sent":
                continue
            service = self.targets.get(target_id)
            if service is None or not service.enabled:
                await self.database.record_target_delivery_skipped(state.listing_id, target_id)
                continue
            try:
                await service.notify_new_listing(listing)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                errors[target_id] = f"{type(error).__name__}: {error}"
                await self.database.record_target_delivery_attempt(
                    state.listing_id,
                    target_id,
                    sent=False,
                    error=str(error),
                )
                logger.error(
                    "target_delivery_failed target_id=%s provider_listing_id=%s error_type=%s",
                    target_id,
                    listing.provider_listing_id,
                    type(error).__name__,
                )
                continue
            await self.database.record_target_delivery_attempt(
                state.listing_id, target_id, sent=True
            )
            logger.info(
                "target_delivery_sent target_id=%s provider_listing_id=%s",
                target_id,
                listing.provider_listing_id,
            )

        if errors:
            raise NotificationDeliveryError(
                "; ".join(f"target {target_id}: {message}" for target_id, message in errors.items())
            )

    async def notify_test(self) -> None:
        raise NotImplementedError(
            "Use notify_test_target(target_id) to test one specific notification target"
        )

    async def notify_test_target(self, target_id: int) -> None:
        service = self.targets.get(target_id)
        if service is None:
            raise NotificationDeliveryError("Unknown notification target")
        await service.notify_test()

    async def close(self) -> None:
        await self.targets.close()
