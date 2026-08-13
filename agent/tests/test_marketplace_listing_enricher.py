from __future__ import annotations

import logging

import pytest

from agent.app.core.exceptions import RequestTimeoutError
from agent.app.core.models import (
    EnrichmentStatus,
    Listing,
    ListingEnrichment,
    SearchCategory,
    SellerType,
)
from agent.app.willhaben.marketplace_listing_enricher import (
    WillhabenMarketplaceListingEnricher,
)


class FakeDetailClient:
    def __init__(
        self,
        details: ListingEnrichment | None = None,
        error: Exception | None = None,
    ) -> None:
        self.details = details
        self.error = error

    async def fetch(self, listing: Listing) -> ListingEnrichment:
        if self.error:
            raise self.error
        assert self.details is not None
        return self.details


def _listing() -> Listing:
    return Listing(
        provider_listing_id="detail-1",
        title="Basis-Titel",
        url="https://www.willhaben.at/iad/object/detail-1",
        category=SearchCategory.MARKETPLACE,
        location="Wien",
    )


@pytest.mark.asyncio
async def test_enricher_merges_complete_details_and_logs_without_personal_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    details = ListingEnrichment(
        title="Detail-Titel",
        price="465",
        image_url="https://cache.willhaben.at/test/main.jpg",
        location="Wien, 22. Bezirk",
        seller_name="Max M.",
        seller_type=SellerType.PRIVATE,
        condition="Sehr gut",
    )
    enricher = WillhabenMarketplaceListingEnricher(FakeDetailClient(details))  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO):
        enriched = await enricher.enrich(_listing())

    assert enriched.enrichment_status is EnrichmentStatus.ENRICHED
    assert enriched.title == "Detail-Titel"
    assert enriched.seller_name == "Max M."
    assert "listing_enrichment_started" in caplog.text
    assert "listing_enrichment_completed" in caplog.text
    assert "Max M." not in caplog.text


@pytest.mark.asyncio
async def test_enricher_marks_valid_incomplete_details_partial() -> None:
    details = ListingEnrichment(location="Wien, 22. Bezirk")
    enricher = WillhabenMarketplaceListingEnricher(FakeDetailClient(details))  # type: ignore[arg-type]

    enriched = await enricher.enrich(_listing())

    assert enriched.enrichment_status is EnrichmentStatus.PARTIAL
    assert enriched.seller_name is None


@pytest.mark.asyncio
async def test_enricher_marks_failure_without_raising() -> None:
    client = FakeDetailClient(error=RequestTimeoutError("simulated"))
    enricher = WillhabenMarketplaceListingEnricher(client)  # type: ignore[arg-type]

    enriched = await enricher.enrich(_listing())

    assert enriched.enrichment_status is EnrichmentStatus.FAILED
