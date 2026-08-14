from __future__ import annotations

import asyncio
import logging

from agent.app.core.article_label import derive_article_label, derive_article_phrase
from agent.app.core.enrichment import ListingEnricher
from agent.app.core.models import EnrichmentStatus, Listing, ListingEnrichment, SearchCategory
from agent.app.willhaben.marketplace_detail_client import WillhabenMarketplaceDetailClient

logger = logging.getLogger(__name__)


class WillhabenMarketplaceListingEnricher(ListingEnricher):
    """Best-effort one-shot enrichment for newly detected Marketplace listings."""

    def __init__(self, client: WillhabenMarketplaceDetailClient | None = None) -> None:
        self.client = client or WillhabenMarketplaceDetailClient()

    async def enrich(self, listing: Listing) -> Listing:
        if listing.category is not SearchCategory.MARKETPLACE:
            return listing
        logger.info(
            "listing_enrichment_started provider_listing_id=%s",
            listing.provider_listing_id,
        )
        try:
            details = await self.client.fetch(listing)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            logger.warning(
                "listing_enrichment_failed provider_listing_id=%s error_type=%s",
                listing.provider_listing_id,
                type(error).__name__,
            )
            return listing.model_copy(update={"enrichment_status": EnrichmentStatus.FAILED})

        status = self._status(details)
        merged_attributes = {**listing.attributes, **details.attributes}
        enriched_title = details.title or listing.title
        article_label = derive_article_label(enriched_title, merged_attributes)
        enriched = listing.model_copy(
            update={
                "title": enriched_title,
                "article_label": article_label,
                "article_phrase": derive_article_phrase(
                    article_label,
                    enriched_title,
                    merged_attributes,
                ),
                "price": details.price if details.price is not None else listing.price,
                "image_url": details.image_url or listing.image_url,
                "location": details.location or listing.location,
                "seller_name": details.seller_name,
                "seller_type": details.seller_type,
                "condition": details.condition,
                "enrichment_status": status,
                "attributes": merged_attributes,
            }
        )
        event = (
            "listing_enrichment_completed"
            if status is EnrichmentStatus.ENRICHED
            else "listing_enrichment_partial"
        )
        logger.info("%s provider_listing_id=%s", event, listing.provider_listing_id)
        return enriched

    @staticmethod
    def _status(details: ListingEnrichment) -> EnrichmentStatus:
        frequently_used = (
            details.seller_name,
            details.seller_type,
            details.condition,
            details.location,
            details.image_url,
        )
        if all(value is not None for value in frequently_used):
            return EnrichmentStatus.ENRICHED
        return EnrichmentStatus.PARTIAL
