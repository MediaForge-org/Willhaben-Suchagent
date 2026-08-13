from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import monotonic

from agent.app.core.exceptions import (
    AccessDeniedError,
    ChallengeDetectedError,
    ProviderError,
    RateLimitedError,
)
from agent.app.core.health import HealthState
from agent.app.core.models import Listing, SearchDefinition
from agent.app.core.provider import ListingProvider
from agent.app.core.time import utc_now
from agent.app.notifications.service import NotificationService
from agent.app.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchOutcome:
    search: SearchDefinition
    listings: list[Listing] | None = None
    error: Exception | None = None


class Scheduler:
    """One cadence loop that evaluates all enabled searches in each cycle."""

    def __init__(
        self,
        *,
        database: Database,
        provider: ListingProvider,
        notification_service: NotificationService,
        health: HealthState,
        cycle_interval_seconds: float,
        max_concurrent_requests: int,
    ) -> None:
        self.database = database
        self.provider = provider
        self.notification_service = notification_service
        self.health = health
        self.cycle_interval_seconds = cycle_interval_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self.health.scheduler_running = True
        self._task = asyncio.create_task(self._run_loop(), name="global-search-scheduler")

    async def stop(self) -> None:
        self.health.scheduler_running = False
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                cycle_started_monotonic = monotonic()
                try:
                    await self.run_cycle()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("cycle_unhandled_failure")
                next_start = cycle_started_monotonic + self.cycle_interval_seconds
                delay = max(0.0, next_start - monotonic())
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                except TimeoutError:
                    continue
        finally:
            self.health.scheduler_running = False

    async def _fetch_one(self, search: SearchDefinition) -> SearchOutcome:
        async with self._semaphore:
            logger.info("search_started search_id=%s", search.id)
            try:
                listings = await self.provider.search(search)
                logger.info(
                    "search_success search_id=%s listings=%s",
                    search.id,
                    len(listings),
                )
                return SearchOutcome(search=search, listings=listings)
            except ProviderError as error:
                log_method = (
                    logger.warning
                    if isinstance(
                        error,
                        (RateLimitedError, AccessDeniedError, ChallengeDetectedError),
                    )
                    else logger.error
                )
                log_method(
                    "search_provider_error search_id=%s error_type=%s",
                    search.id,
                    type(error).__name__,
                )
                return SearchOutcome(search=search, error=error)
            except Exception as error:
                logger.error(
                    "search_unexpected_error search_id=%s error_type=%s",
                    search.id,
                    type(error).__name__,
                )
                return SearchOutcome(search=search, error=error)

    async def _deliver_pending_notifications(self) -> tuple[int, int]:
        pending = await self.database.list_deliverable_notifications()
        if not pending:
            return 0, 0
        for notification in pending:
            logger.info(
                "notification_pending notification_id=%s provider_listing_id=%s attempt=%s",
                notification.id,
                notification.listing.provider_listing_id,
                notification.attempt_count + 1,
            )
        if not self.notification_service.enabled:
            logger.info(
                "notification_delivery_disabled pending=%s reason=%s",
                len(pending),
                self.notification_service.disabled_reason,
            )
            return 0, 0

        sent_count = 0
        failed_count = 0
        for notification in pending:
            try:
                await self.notification_service.notify_new_listing(notification.listing)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failed_count += 1
                self.health.last_notification_error = type(error).__name__
                await self.database.mark_notification_failed(
                    notification.id,
                    f"{type(error).__name__}: {error}",
                )
                logger.error(
                    "notification_failed notification_id=%s provider_listing_id=%s error_type=%s",
                    notification.id,
                    notification.listing.provider_listing_id,
                    type(error).__name__,
                )
                continue
            await self.database.mark_notification_sent(notification.id)
            sent_count += 1
            self.health.last_successful_notification_at = utc_now()
            logger.info(
                "notification_sent notification_id=%s provider_listing_id=%s",
                notification.id,
                notification.listing.provider_listing_id,
            )
        if failed_count == 0:
            self.health.last_notification_error = None
        return sent_count, failed_count

    async def run_cycle(self) -> None:
        started_monotonic = monotonic()
        self.health.last_cycle_started_at = utc_now()
        self.health.total_cycle_count += 1
        self.health.last_cycle_error = None
        self.health.last_provider_errors = {}
        logger.info("cycle_started cycle=%s", self.health.total_cycle_count)

        try:
            searches = await self.database.list_searches(enabled_only=True)
            logger.info("cycle_active_searches count=%s", len(searches))
            outcomes = await asyncio.gather(*(self._fetch_one(search) for search in searches))

            successful_results: list[tuple[SearchDefinition, list[Listing]]] = []
            for outcome in outcomes:
                if outcome.error is not None:
                    await self.database.record_search_failure(outcome.search.id)
                    self.health.last_provider_errors[outcome.search.id] = type(
                        outcome.error
                    ).__name__
                else:
                    successful_results.append((outcome.search, outcome.listings or []))

            persistence = await self.database.persist_cycle_results(successful_results)
            sent_count, notification_failures = await self._deliver_pending_notifications()

            if searches and not self.health.last_provider_errors:
                successful_at = utc_now()
                self.health.last_successful_cycle_at = successful_at
                self.health.last_successful_willhaben_cycle_at = successful_at
            logger.info(
                "cycle_results listings=%s new_listings=%s notifications_pending=%s "
                "notifications_sent=%s notification_failures=%s baselines=%s",
                sum(len(listings) for _, listings in successful_results),
                persistence.new_listing_count,
                persistence.created_notification_count,
                sent_count,
                notification_failures,
                persistence.baseline_initializations,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.health.failed_cycle_count += 1
            self.health.last_cycle_error = type(error).__name__
            logger.exception("cycle_failed cycle=%s", self.health.total_cycle_count)
            raise
        finally:
            duration = monotonic() - started_monotonic
            self.health.last_cycle_completed_at = utc_now()
            self.health.last_cycle_duration_seconds = duration
            logger.info(
                "cycle_completed cycle=%s duration_seconds=%.3f",
                self.health.total_cycle_count,
                duration,
            )
