import asyncio
from collections.abc import Callable
from time import monotonic

from agent.app.core.models import Listing, SearchDefinition
from agent.app.core.provider import ListingProvider


class FakeListingProvider(ListingProvider):
    """Deterministic in-memory provider used by M1 and its test suite."""

    def __init__(self, delay_seconds: float = 0) -> None:
        self._results: dict[int, list[Listing]] = {}
        self._errors: dict[int, Exception | Callable[[], Exception]] = {}
        self.delay_seconds = delay_seconds
        self.calls: list[int] = []
        self.call_started_at: list[float] = []
        self._calls_changed = asyncio.Condition()
        self.active_requests = 0
        self.max_observed_concurrency = 0

    def set_results(self, search_id: int, listings: list[Listing]) -> None:
        self._results[search_id] = listings
        self._errors.pop(search_id, None)

    def set_error(
        self,
        search_id: int,
        error: Exception | Callable[[], Exception],
    ) -> None:
        self._errors[search_id] = error

    async def search(self, search_definition: SearchDefinition) -> list[Listing]:
        async with self._calls_changed:
            self.calls.append(search_definition.id)
            self.call_started_at.append(monotonic())
            self._calls_changed.notify_all()
        self.active_requests += 1
        self.max_observed_concurrency = max(self.max_observed_concurrency, self.active_requests)
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            configured_error = self._errors.get(search_definition.id)
            if configured_error is not None:
                error = configured_error() if callable(configured_error) else configured_error
                raise error
            return list(self._results.get(search_definition.id, []))
        finally:
            self.active_requests -= 1

    async def wait_for_call_count(self, count: int) -> None:
        """Wait until at least ``count`` provider calls have started."""

        async with self._calls_changed:
            await self._calls_changed.wait_for(lambda: len(self.calls) >= count)
