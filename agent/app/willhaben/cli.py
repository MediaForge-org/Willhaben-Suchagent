from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal

from agent.app.core.config import Settings
from agent.app.core.exceptions import ProviderError
from agent.app.core.logging import configure_logging
from agent.app.core.models import SearchCategory, SearchDefinition
from agent.app.core.time import utc_now
from agent.app.willhaben.marketplace_provider import WillhabenMarketplaceProvider


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one public, unauthenticated Willhaben Marketplace search."
    )
    parser.add_argument("query", help="Marketplace search term")
    parser.add_argument("--price-from", type=Decimal)
    parser.add_argument("--price-to", type=Decimal)
    parser.add_argument("--location", help="Austrian Bundesland, Wien, or areaId")
    parser.add_argument(
        "--category",
        help="Supported category name, ID, or complete Willhaben SEO category segment",
    )
    parser.add_argument("--limit", type=int, default=5, help="Number of listings to print")
    return parser.parse_args()


async def _run(arguments: argparse.Namespace) -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    timestamp = utc_now()
    search = SearchDefinition(
        id=0,
        name="Manual Marketplace search",
        category=SearchCategory.MARKETPLACE,
        query=arguments.query,
        location=arguments.location,
        price_min=arguments.price_from,
        price_max=arguments.price_to,
        category_filters=(
            {"marketplace_category": arguments.category} if arguments.category else {}
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )
    provider = WillhabenMarketplaceProvider(
        user_agent=settings.marketplace_user_agent,
        connect_timeout_seconds=settings.marketplace_connect_timeout_seconds,
        read_timeout_seconds=settings.marketplace_read_timeout_seconds,
        max_redirects=settings.marketplace_max_redirects,
        max_response_bytes=settings.marketplace_max_response_bytes,
    )
    listings = await provider.search(search)
    print(f"Gefundene Inserate: {len(listings)}")
    for listing in listings[: max(0, arguments.limit)]:
        price = f"€ {listing.price}" if listing.price is not None else "kein Preis"
        print(f"{listing.provider_listing_id} | {listing.title} | {price}")
        print(str(listing.url))


def main() -> None:
    try:
        asyncio.run(_run(_arguments()))
    except ProviderError as error:
        raise SystemExit(f"{type(error).__name__}: {error}") from None


if __name__ == "__main__":
    main()
