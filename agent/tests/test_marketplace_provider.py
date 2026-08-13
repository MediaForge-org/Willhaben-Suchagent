from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from agent.app.core.exceptions import (
    AccessDeniedError,
    ChallengeDetectedError,
    NetworkError,
    ParseError,
    ProviderInternalError,
    RateLimitedError,
    RequestTimeoutError,
)
from agent.app.core.models import SearchCategory, SearchDefinition
from agent.app.core.scheduler import Scheduler
from agent.app.storage.database import Database, SearchCreateData
from agent.app.willhaben.marketplace_provider import WillhabenMarketplaceProvider

FIXTURE = Path(__file__).parent / "fixtures" / "willhaben" / "marketplace_search.html"


def _search() -> SearchDefinition:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return SearchDefinition(
        id=42,
        name="ThinkPad",
        category=SearchCategory.MARKETPLACE,
        query="thinkpad",
        created_at=timestamp,
        updated_at=timestamp,
    )


async def _search_with_handler(handler: httpx.MockTransport) -> list[object]:
    async with httpx.AsyncClient(transport=handler, follow_redirects=True) as client:
        provider = WillhabenMarketplaceProvider(client=client)
        return await provider.search(_search())


@pytest.mark.asyncio
async def test_provider_fetches_public_html_and_sends_configured_headers() -> None:
    html = FIXTURE.read_text(encoding="utf-8")

    def response(request: httpx.Request) -> httpx.Response:
        assert request.url.params["keyword"] == "thinkpad"
        assert request.url.params["sort"] == "1"
        assert request.headers["user-agent"].startswith("Willhaben-Suchagent/0.3")
        return httpx.Response(200, text=html, headers={"content-type": "text/html"})

    listings = await _search_with_handler(httpx.MockTransport(response))

    assert len(listings) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(429, RateLimitedError), (403, AccessDeniedError), (500, ProviderInternalError)],
)
async def test_provider_classifies_http_status(
    status_code: int,
    error_type: type[Exception],
) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(status_code, request=request))

    with pytest.raises(error_type):
        await _search_with_handler(transport)


@pytest.mark.asyncio
async def test_provider_detects_challenge_page() -> None:
    body = "<html><head><title>Security Challenge</title></head><div class='g-recaptcha'></div>"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/html"},
            request=request,
        )
    )

    with pytest.raises(ChallengeDetectedError):
        await _search_with_handler(transport)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_error", "provider_error"),
    [
        (httpx.ReadTimeout("simulated timeout"), RequestTimeoutError),
        (httpx.ConnectError("simulated connection failure"), NetworkError),
    ],
)
async def test_provider_classifies_transport_errors(
    transport_error: httpx.RequestError,
    provider_error: type[Exception],
) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        transport_error.request = request
        raise transport_error

    with pytest.raises(provider_error):
        await _search_with_handler(httpx.MockTransport(fail))


@pytest.mark.asyncio
async def test_provider_rejects_unexpected_content() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"unexpected": True},
            headers={"content-type": "application/json"},
            request=request,
        )
    )

    with pytest.raises(ParseError):
        await _search_with_handler(transport)


@pytest.mark.asyncio
async def test_real_provider_integrates_with_scheduler_baseline(
    database: Database,
    scheduler_factory,
) -> None:
    search = await database.create_search(
        SearchCreateData(
            name="ThinkPad",
            category=SearchCategory.MARKETPLACE,
            enabled=True,
            query="thinkpad",
            location=None,
            price_min=Decimal("10"),
            price_max=Decimal("500"),
            category_filters={},
        )
    )
    html = FIXTURE.read_text(encoding="utf-8")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html"},
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        provider = WillhabenMarketplaceProvider(client=client)
        scheduler: Scheduler = scheduler_factory(provider=provider)
        await scheduler.run_cycle()

    refreshed = await database.get_search(search.id)
    assert refreshed is not None
    assert refreshed.baseline_initialized is True
    assert await database.count("listings") == 2
    assert await database.count("search_matches") == 2
