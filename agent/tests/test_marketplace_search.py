from datetime import UTC, datetime
from decimal import Decimal

import pytest

from agent.app.core.models import SearchCategory, SearchDefinition
from agent.app.willhaben.marketplace_search import (
    MarketplaceSearchBuilder,
    UnsupportedMarketplaceSearch,
)


def _search(**changes: object) -> SearchDefinition:
    values: dict[str, object] = {
        "id": 42,
        "name": "ThinkPad",
        "category": SearchCategory.MARKETPLACE,
        "query": "ThinkPad X1",
        "location": None,
        "price_min": None,
        "price_max": None,
        "category_filters": {},
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(changes)
    return SearchDefinition.model_validate(values)


def test_search_builder_creates_deterministic_request_with_newest_first() -> None:
    builder = MarketplaceSearchBuilder()
    search = _search()

    first = builder.build(search)
    second = builder.build(search)

    assert first == second
    assert str(first.url) == (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=ThinkPad+X1&sort=1"
    )
    assert first.url.params["keyword"] == "ThinkPad X1"
    assert first.url.params["sort"] == "1"


def test_search_builder_maps_prices_and_region() -> None:
    request = MarketplaceSearchBuilder().build(
        _search(
            price_min=Decimal("100.00"),
            price_max=Decimal("1200.50"),
            location="Niederösterreich",
        )
    )

    assert list(request.url.params.multi_items()) == [
        ("keyword", "ThinkPad X1"),
        ("PRICE_FROM", "100"),
        ("PRICE_TO", "1200.5"),
        ("areaId", "3"),
        ("sort", "1"),
    ]


@pytest.mark.parametrize(
    ("category", "path"),
    [
        ("Computer / Software", "computer-software-5824"),
        ("5824", "computer-software-5824"),
        ("computer-software-5824", "computer-software-5824"),
    ],
)
def test_search_builder_maps_marketplace_category(category: str, path: str) -> None:
    request = MarketplaceSearchBuilder().build(
        _search(category_filters={"marketplace_category": category})
    )

    assert request.url.path.endswith(f"/marktplatz/{path}")


def test_search_builder_rejects_unverified_filters() -> None:
    with pytest.raises(UnsupportedMarketplaceSearch):
        MarketplaceSearchBuilder().build(_search(category_filters={"condition": "used"}))
