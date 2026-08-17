from decimal import Decimal

import pytest

from agent.app.willhaben.search_url_import import (
    InvalidSearchUrlError,
    parse_marketplace_search_url,
)

IPHONE_URL = (
    "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/apple/"
    "iphone-13-mini-5009987?keyword=iphone+13+mini&sfId=d16702ad-e779-4fc3-b3b5-"
    "4442c66247a9&rows=30&isNavigation=true"
)


def test_iphone_example_url_extracts_deep_category_and_keyword_and_drops_navigation_params() -> (
    None
):
    draft = parse_marketplace_search_url(IPHONE_URL)

    assert draft.category_path == "apple/iphone-13-mini-5009987"
    assert draft.category_label == "Apple → iPhone 13 Mini"
    assert draft.query == "iphone 13 mini"
    assert draft.location is None
    assert draft.price_min is None
    assert draft.price_max is None
    assert draft.unsupported_filters == []


def test_price_and_region_filters_are_mapped() -> None:
    url = (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/"
        "computer-software-5824?PRICE_FROM=100&PRICE_TO=500&areaId=900&keyword=thinkpad"
    )

    draft = parse_marketplace_search_url(url)

    assert draft.category_path == "computer-software-5824"
    assert draft.category_label == "Computer & Software"
    assert draft.price_min == Decimal("100")
    assert draft.price_max == Decimal("500")
    assert draft.location == "Wien"
    assert draft.query == "thinkpad"


def test_category_without_keyword_is_valid() -> None:
    url = (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/apple/iphone-13-mini-5009987"
    )

    draft = parse_marketplace_search_url(url)

    assert draft.category_path == "apple/iphone-13-mini-5009987"
    assert draft.query == ""


def test_top_level_marketplace_url_without_category_is_valid() -> None:
    url = "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=lampe"

    draft = parse_marketplace_search_url(url)

    assert draft.category_path is None
    assert draft.category_label is None
    assert draft.query == "lampe"


def test_unrecognized_filter_is_reported_not_silently_dropped() -> None:
    url = (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/"
        "apple/iphone-13-mini-5009987?keyword=iphone&CONDITION=neu"
    )

    draft = parse_marketplace_search_url(url)

    assert any("CONDITION" in message for message in draft.unsupported_filters)


def test_non_default_sort_is_reported_and_not_silently_applied() -> None:
    url = (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/"
        "apple/iphone-13-mini-5009987?keyword=iphone&sort=2"
    )

    draft = parse_marketplace_search_url(url)

    assert any("Sortierung" in message for message in draft.unsupported_filters)


def test_default_sort_value_is_not_reported() -> None:
    url = (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/"
        "apple/iphone-13-mini-5009987?keyword=iphone&sort=1"
    )

    draft = parse_marketplace_search_url(url)

    assert draft.unsupported_filters == []


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/iad/kaufen-und-verkaufen/marktplatz/apple/iphone-13-mini-5009987",
        "http://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/apple/iphone-13-mini-5009987",
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://localhost/iad/kaufen-und-verkaufen/marktplatz",
        "https://willhaben.at.attacker.test/iad/kaufen-und-verkaufen/marktplatz",
        "https://www.willhaben.at:8443/iad/kaufen-und-verkaufen/marktplatz",
        "https://user:pass@www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz",
        "https://www.willhaben.at/iad/gebrauchtwagen/auto/bmw",
        "https://www.willhaben.at/iad/immobilien/mietwohnungen",
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/apple/../../etc",
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/Apple/UPPERCASE-1",
        "not a url",
        "",
    ],
)
def test_rejects_unsafe_or_unsupported_urls(url: str) -> None:
    with pytest.raises(InvalidSearchUrlError):
        parse_marketplace_search_url(url)


def test_rejects_overly_long_url() -> None:
    with pytest.raises(InvalidSearchUrlError):
        parse_marketplace_search_url("https://www.willhaben.at/" + "a" * 3000)
