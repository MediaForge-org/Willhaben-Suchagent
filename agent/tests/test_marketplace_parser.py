from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from agent.app.core.exceptions import ChallengeDetectedError, ParseError
from agent.app.core.models import SearchCategory
from agent.app.willhaben.marketplace_parser import WillhabenMarketplaceParser

FIXTURE = Path(__file__).parent / "fixtures" / "willhaben" / "marketplace_search.html"


@pytest.fixture
def marketplace_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def _page_state(html: str) -> dict[str, object]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


def _html(state: dict[str, object]) -> str:
    return (
        '<!doctype html><html><body><script id="__NEXT_DATA__" '
        f'type="application/json">{json.dumps(state)}</script></body></html>'
    )


def _adverts(state: dict[str, object]) -> list[dict[str, object]]:
    return state["props"]["pageProps"]["searchResult"]["advertSummaryList"][  # type: ignore[index]
        "advertSummary"
    ]


def test_public_marketplace_response_maps_multiple_listings(marketplace_html: str) -> None:
    listings = WillhabenMarketplaceParser().parse(marketplace_html)

    assert len(listings) == 2
    first = listings[0]
    assert first.provider_listing_id == "9000000001"
    assert first.title == "ThinkPad Ersatzteil"
    assert first.price == Decimal("10.0")
    assert str(first.url) == (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/d/thinkpad-ersatzteil-9000000001/"
    )
    assert str(first.image_url) == ("https://cache.willhaben.at/mmo/1/900/000/0001_100_hoved.jpg")
    assert first.category is SearchCategory.MARKETPLACE
    assert first.location == "Wien"
    assert first.attributes == {
        "ad_type_id": "67",
        "changed_at": "2026-08-13T02:58:48Z",
        "district": "Wien",
        "is_private": True,
        "marketplace_category_ids": ["5824", "5878", "5884"],
        "paylivery_enabled": True,
        "postcode": "1000",
        "product_id": "67",
        "published_at": "2026-08-13T02:58:48Z",
        "state": "Wien",
    }


def test_missing_optional_fields_do_not_break_result(marketplace_html: str) -> None:
    state = _page_state(marketplace_html)
    advert = _adverts(state)[0]
    attributes = advert["attributes"]["attribute"]  # type: ignore[index]
    advert["attributes"]["attribute"] = [  # type: ignore[index]
        item
        for item in attributes
        if item["name"] not in {"LOCATION", "PRICE/AMOUNT", "STATE", "POSTCODE"}
    ]
    advert.pop("advertImageList")

    listing = WillhabenMarketplaceParser().parse(_html(state))[0]

    assert listing.price is None
    assert listing.image_url is None
    assert listing.location is None


def test_one_malformed_listing_does_not_discard_valid_listings(marketplace_html: str) -> None:
    state = _page_state(marketplace_html)
    _adverts(state).insert(0, {"description": "missing stable ID"})

    listings = WillhabenMarketplaceParser().parse(_html(state))

    assert [listing.provider_listing_id for listing in listings] == ["9000000001", "9000000002"]


def test_empty_result_list_is_valid(marketplace_html: str) -> None:
    state = _page_state(marketplace_html)
    result = state["props"]["pageProps"]["searchResult"]  # type: ignore[index]
    result["rowsFound"] = 0
    result["rowsReturned"] = 0
    result["advertSummaryList"]["advertSummary"] = []

    assert WillhabenMarketplaceParser().parse(_html(state)) == []


@pytest.mark.parametrize(
    "body",
    [
        "not html or JSON",
        '<html><script id="__NEXT_DATA__" type="application/json">{broken</script></html>',
        '<html><script id="__NEXT_DATA__" type="application/json">{}</script></html>',
    ],
)
def test_broken_response_raises_parse_error(body: str) -> None:
    with pytest.raises(ParseError):
        WillhabenMarketplaceParser().parse(body)


def test_challenge_page_raises_challenge_detected() -> None:
    body = "<html><head><title>Security Challenge</title></head><div class='g-recaptcha'></div>"

    with pytest.raises(ChallengeDetectedError):
        WillhabenMarketplaceParser().parse(body)
