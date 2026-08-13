from __future__ import annotations

import logging

import httpx

from agent.app.core.exceptions import (
    AccessDeniedError,
    ChallengeDetectedError,
    ParseError,
    ProviderInternalError,
    RateLimitedError,
)
from agent.app.core.models import Listing, SearchDefinition
from agent.app.core.provider import ListingProvider
from agent.app.willhaben.http_client import WillhabenHttpClient
from agent.app.willhaben.marketplace_parser import WillhabenMarketplaceParser
from agent.app.willhaben.marketplace_search import (
    MarketplaceSearchBuilder,
    UnsupportedMarketplaceSearch,
)

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "Willhaben-Suchagent/0.2 (public Marketplace search; no authentication)"


class WillhabenMarketplaceProvider(ListingProvider):
    """Retrieve and normalize public Willhaben Marketplace search pages."""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        connect_timeout_seconds: float = 10,
        read_timeout_seconds: float = 20,
        max_redirects: int = 3,
        max_response_bytes: int = 5_000_000,
        client: httpx.AsyncClient | None = None,
        search_builder: MarketplaceSearchBuilder | None = None,
        parser: WillhabenMarketplaceParser | None = None,
    ) -> None:
        self.search_builder = search_builder or MarketplaceSearchBuilder()
        self.parser = parser or WillhabenMarketplaceParser()
        self.http_client = WillhabenHttpClient(
            user_agent=user_agent,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            max_redirects=max_redirects,
            max_response_bytes=max_response_bytes,
            client=client,
        )

    async def search(self, search_definition: SearchDefinition) -> list[Listing]:
        logger.info("marketplace_request_started search_id=%s", search_definition.id)
        try:
            request = self.search_builder.build(search_definition)
        except UnsupportedMarketplaceSearch as error:
            raise ProviderInternalError(str(error)) from error

        response = await self.http_client.get(request.url)
        logger.info(
            "marketplace_response search_id=%s http_status=%s",
            search_definition.id,
            response.status_code,
        )
        if response.status_code == 429:
            raise RateLimitedError("Willhaben rate limited the public search request")
        if response.status_code == 403:
            raise AccessDeniedError("Willhaben denied the public search request")
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderInternalError(f"Unexpected Willhaben HTTP status {response.status_code}")

        content_type = response.headers.get("content-type", "").casefold()
        if (
            content_type
            and "text/html" not in content_type
            and "application/xhtml+xml" not in content_type
        ):
            raise ParseError("Willhaben returned an unexpected content type")
        try:
            listings = self.parser.parse(response.text)
        except ChallengeDetectedError:
            logger.warning("marketplace_challenge_detected search_id=%s", search_definition.id)
            raise
        except ParseError:
            logger.error("marketplace_parse_failed search_id=%s", search_definition.id)
            raise
        logger.info(
            "marketplace_response_parsed search_id=%s listings=%s",
            search_definition.id,
            len(listings),
        )
        return listings
