from __future__ import annotations

import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

from agent.app.core.exceptions import ChallengeDetectedError, ParseError
from agent.app.core.models import SellerType
from agent.app.willhaben.marketplace_detail_parser import WillhabenMarketplaceDetailParser

FIXTURE = Path(__file__).parent / "fixtures" / "willhaben" / "marketplace_detail.html"


@pytest.fixture
def detail_html() -> str:
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


def _details(state: dict[str, object]) -> dict[str, object]:
    return state["props"]["pageProps"]["advertDetails"]  # type: ignore[index]


def test_real_detail_structure_maps_public_enrichment_fields(detail_html: str) -> None:
    details = WillhabenMarketplaceDetailParser().parse(
        detail_html,
        expected_listing_id="9000000100",
    )

    assert details.title == "Lenovo ThinkPad T14 G3"
    assert details.price == Decimal("465")
    assert details.seller_name == "Beispiel Technik GmbH"
    assert details.seller_type is SellerType.COMMERCIAL
    assert details.condition == "Sehr gut"
    assert details.location == "Wien, 22. Bezirk, Donaustadt"
    assert str(details.image_url) == "https://cache.willhaben.at/test/thinkpad-main.jpg"
    assert details.attributes["published_at"] == "2026-08-13T08:05:00Z"
    assert details.attributes["category_path"][-1] == "Notebooks"
    assert details.attributes["public_attributes"]["Marke"] == ["Lenovo"]


def test_private_seller_name_and_type_are_mapped(detail_html: str) -> None:
    state = _page_state(detail_html)
    details = _details(state)
    details["sellerProfileUserData"]["name"] = "Max M."  # type: ignore[index]
    details["sellerProfileUserData"]["private"] = True  # type: ignore[index]
    details["organisationDetails"] = {}

    parsed = WillhabenMarketplaceDetailParser().parse(_html(state))

    assert parsed.seller_name == "Max M."
    assert parsed.seller_type is SellerType.PRIVATE


def test_missing_seller_name_is_valid(detail_html: str) -> None:
    state = _page_state(detail_html)
    details = _details(state)
    details["sellerProfileUserData"]["name"] = None  # type: ignore[index]
    details["organisationDetails"] = {}
    details["taggingData"]["tmsDataValues"]["tmsData"]["seller_name"] = None  # type: ignore[index]

    assert WillhabenMarketplaceDetailParser().parse(_html(state)).seller_name is None


def test_missing_condition_is_valid(detail_html: str) -> None:
    state = _page_state(detail_html)
    details = _details(state)
    details["attributeInformation"] = [
        item
        for item in details["attributeInformation"]  # type: ignore[union-attr]
        if item["treeAttributeElement"]["code"] != "Zustand"
    ]

    assert WillhabenMarketplaceDetailParser().parse(_html(state)).condition is None


def test_missing_location_is_valid(detail_html: str) -> None:
    state = _page_state(detail_html)
    details = _details(state)
    details["sellerProfileUserData"]["location"] = None  # type: ignore[index]
    details["advertAddressDetails"] = {}

    assert WillhabenMarketplaceDetailParser().parse(_html(state)).location is None


@pytest.mark.parametrize(
    "body",
    [
        "",
        "<html>no page state</html>",
        '<script id="__NEXT_DATA__" type="application/json">{broken</script>',
    ],
)
def test_invalid_detail_page_raises_parse_error(body: str) -> None:
    with pytest.raises(ParseError):
        WillhabenMarketplaceDetailParser().parse(body)


def test_unexpected_listing_id_raises_parse_error(detail_html: str) -> None:
    with pytest.raises(ParseError):
        WillhabenMarketplaceDetailParser().parse(
            detail_html,
            expected_listing_id="different-listing",
        )


def test_detail_challenge_page_is_classified() -> None:
    body = "<html><head><title>Security Challenge</title></head><div>g-recaptcha</div>"
    with pytest.raises(ChallengeDetectedError):
        WillhabenMarketplaceDetailParser().parse(body)


def test_committed_detail_fixture_contains_only_synthetic_contact_data(
    detail_html: str,
) -> None:
    assert "Beispiel Technik GmbH" in detail_html
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", detail_html)
    assert not re.search(r"(?:\+43|0043)[\d\s/-]{7,}", detail_html)
