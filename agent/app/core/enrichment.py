from abc import ABC, abstractmethod

from agent.app.core.models import Listing


class ListingEnricher(ABC):
    """Provider-independent boundary for optional one-shot listing enrichment."""

    @abstractmethod
    async def enrich(self, listing: Listing) -> Listing:
        """Return the listing with public detail information or a failure status."""
