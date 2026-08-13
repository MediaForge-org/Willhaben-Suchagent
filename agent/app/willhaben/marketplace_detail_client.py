from __future__ import annotations

import httpx

from agent.app.core.exceptions import (
    AccessDeniedError,
    ParseError,
    ProviderInternalError,
    RateLimitedError,
)
from agent.app.core.models import Listing, ListingEnrichment
from agent.app.willhaben.http_client import WillhabenHttpClient
from agent.app.willhaben.marketplace_detail_parser import WillhabenMarketplaceDetailParser
from agent.app.willhaben.marketplace_provider import DEFAULT_USER_AGENT


class WillhabenMarketplaceDetailClient:
    """Fetch and parse exactly one public Marketplace listing detail page."""

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        connect_timeout_seconds: float = 10,
        read_timeout_seconds: float = 20,
        max_redirects: int = 3,
        max_response_bytes: int = 5_000_000,
        client: httpx.AsyncClient | None = None,
        parser: WillhabenMarketplaceDetailParser | None = None,
    ) -> None:
        self.parser = parser or WillhabenMarketplaceDetailParser()
        self.http_client = WillhabenHttpClient(
            user_agent=user_agent,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            max_redirects=max_redirects,
            max_response_bytes=max_response_bytes,
            client=client,
        )

    async def fetch(self, listing: Listing) -> ListingEnrichment:
        response = await self.http_client.get(httpx.URL(str(listing.url)))
        if response.status_code == 429:
            raise RateLimitedError("Willhaben rate limited the public detail request")
        if response.status_code == 403:
            raise AccessDeniedError("Willhaben denied the public detail request")
        if response.status_code < 200 or response.status_code >= 300:
            raise ProviderInternalError(
                f"Unexpected Willhaben detail HTTP status {response.status_code}"
            )
        content_type = response.headers.get("content-type", "").casefold()
        if (
            content_type
            and "text/html" not in content_type
            and "application/xhtml+xml" not in content_type
        ):
            raise ParseError("Willhaben returned an unexpected detail content type")
        return self.parser.parse(
            response.text,
            expected_listing_id=listing.provider_listing_id,
        )
