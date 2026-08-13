from abc import ABC, abstractmethod

from agent.app.core.models import Listing, SearchDefinition


class ListingProvider(ABC):
    """Boundary between orchestration and provider-specific retrieval/parsing."""

    @abstractmethod
    async def search(self, search_definition: SearchDefinition) -> list[Listing]:
        """Return normalized listings matching one search definition."""
