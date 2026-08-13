from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent.app.core.exceptions import (
    AccessDeniedError,
    ChallengeDetectedError,
    RateLimitedError,
    RequestTimeoutError,
)
from agent.app.core.models import Listing, SearchCategory
from agent.app.willhaben.marketplace_detail_client import WillhabenMarketplaceDetailClient

FIXTURE = Path(__file__).parent / "fixtures" / "willhaben" / "marketplace_detail.html"


def _listing() -> Listing:
    return Listing(
        provider_listing_id="9000000100",
        title="Search result title",
        url=(
            "https://www.willhaben.at/iad/kaufen-und-verkaufen/d/lenovo-thinkpad-t14-g3-9000000100/"
        ),
        category=SearchCategory.MARKETPLACE,
    )


@pytest.mark.asyncio
async def test_detail_client_fetches_exact_public_listing_url_once() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            text=FIXTURE.read_text(encoding="utf-8"),
            headers={"content-type": "text/html"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        details = await WillhabenMarketplaceDetailClient(client=client).fetch(_listing())

    assert len(requests) == 1
    assert str(requests[0].url) == str(_listing().url)
    assert details.seller_name == "Beispiel Technik GmbH"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(403, AccessDeniedError), (429, RateLimitedError)],
)
async def test_detail_client_classifies_protection_statuses(
    status_code: int,
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(error_type):
            await WillhabenMarketplaceDetailClient(client=client).fetch(_listing())


@pytest.mark.asyncio
async def test_detail_client_classifies_timeout() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(RequestTimeoutError):
            await WillhabenMarketplaceDetailClient(client=client).fetch(_listing())


@pytest.mark.asyncio
async def test_detail_client_classifies_challenge() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="<html><title>Security Challenge</title><div>g-recaptcha</div></html>",
            headers={"content-type": "text/html"},
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ChallengeDetectedError):
            await WillhabenMarketplaceDetailClient(client=client).fetch(_listing())
