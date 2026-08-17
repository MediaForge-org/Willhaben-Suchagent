from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

import httpx

from agent.app.core.models import SearchCategory, SearchDefinition

MARKETPLACE_BASE_URL = "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz"
NEWEST_FIRST_SORT = "1"

_REGION_IDS = {
    "burgenland": "1",
    "karnten": "2",
    "niederosterreich": "3",
    "oberosterreich": "4",
    "salzburg": "5",
    "steiermark": "6",
    "tirol": "7",
    "vorarlberg": "8",
    "wien": "900",
    "andere lander": "22000",
}

# These top-level categories and SEO paths were present in the captured public search state.
_CATEGORY_PATHS = {
    "387": "buecher-filme-musik-387",
    "buecher-filme-musik": "buecher-filme-musik-387",
    "bucher-filme-musik": "buecher-filme-musik-387",
    "buecher / filme / musik": "buecher-filme-musik-387",
    "bucher / filme / musik": "buecher-filme-musik-387",
    "5824": "computer-software-5824",
    "computer-software": "computer-software-5824",
    "computer / software": "computer-software-5824",
    "537": "dienstleistungen-537",
    "dienstleistungen": "dienstleistungen-537",
    "6462": "freizeit-instrumente-kulinarik-6462",
    "freizeit-instrumente-kulinarik": "freizeit-instrumente-kulinarik-6462",
    "freizeit / instrumente / kulinarik": "freizeit-instrumente-kulinarik-6462",
    "6142": "kfz-zubehoer-motorradteile-6142",
    "kfz-zubehor-motorradteile": "kfz-zubehoer-motorradteile-6142",
    "kfz-zubehoer-motorradteile": "kfz-zubehoer-motorradteile-6142",
    "kfz-zubehor / motorradteile": "kfz-zubehoer-motorradteile-6142",
    "3275": "mode-accessoires-3275",
    "mode-accessoires": "mode-accessoires-3275",
    "mode / accessoires": "mode-accessoires-3275",
    "2691": "smartphones-telefonie-2691",
    "smartphones-telefonie": "smartphones-telefonie-2691",
    "smartphones / telefonie": "smartphones-telefonie-2691",
    "5387": "wohnen-haushalt-gastronomie-5387",
    "wohnen-haushalt-gastronomie": "wohnen-haushalt-gastronomie-5387",
    "wohnen / haushalt / gastronomie": "wohnen-haushalt-gastronomie-5387",
}

SUPPORTED_MARKETPLACE_CATEGORIES = (
    ("Bücher, Filme & Musik", "buecher-filme-musik-387"),
    ("Computer & Software", "computer-software-5824"),
    ("Dienstleistungen", "dienstleistungen-537"),
    ("Freizeit, Instrumente & Kulinarik", "freizeit-instrumente-kulinarik-6462"),
    ("KFZ-Zubehör & Motorradteile", "kfz-zubehoer-motorradteile-6142"),
    ("Mode & Accessoires", "mode-accessoires-3275"),
    ("Smartphones & Telefonie", "smartphones-telefonie-2691"),
    ("Wohnen, Haushalt & Gastronomie", "wohnen-haushalt-gastronomie-5387"),
)
_CATEGORY_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


SUPPORTED_MARKETPLACE_LOCATIONS = (
    "Burgenland",
    "Kärnten",
    "Niederösterreich",
    "Oberösterreich",
    "Salzburg",
    "Steiermark",
    "Tirol",
    "Vorarlberg",
    "Wien",
)


def _normalized_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().casefold())
    return "".join(character for character in text if not unicodedata.combining(character))


_AREA_ID_TO_LOCATION = {
    _REGION_IDS[_normalized_key(name)]: name for name in SUPPORTED_MARKETPLACE_LOCATIONS
}


def region_name_for_area_id(area_id: str) -> str | None:
    """Reverse-lookup a Willhaben ``areaId`` back to the canonical display name."""

    return _AREA_ID_TO_LOCATION.get(area_id.strip())


class UnsupportedMarketplaceSearch(ValueError):
    """A SearchDefinition contains a filter not supported by the public builder."""


@dataclass(frozen=True, slots=True)
class MarketplaceSearchRequest:
    url: httpx.URL


class MarketplaceSearchBuilder:
    """Build one deterministic public Marketplace page request."""

    def build(self, search: SearchDefinition) -> MarketplaceSearchRequest:
        if search.category is not SearchCategory.MARKETPLACE:
            raise UnsupportedMarketplaceSearch("Only marketplace searches are supported")

        path = MARKETPLACE_BASE_URL
        category = search.category_filters.get("marketplace_category")
        unsupported = set(search.category_filters) - {
            "marketplace_category",
            "marketplace_category_label",
        }
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise UnsupportedMarketplaceSearch(f"Unsupported Marketplace filters: {names}")
        if category is not None:
            path = f"{path}/{self._category_path(category)}"

        parameters: list[tuple[str, str]] = []
        query = search.query.strip()
        if query:
            parameters.append(("keyword", query))
        if search.price_min is not None:
            parameters.append(("PRICE_FROM", self._decimal_parameter(search.price_min)))
        if search.price_max is not None:
            parameters.append(("PRICE_TO", self._decimal_parameter(search.price_max)))
        if search.location:
            parameters.append(("areaId", self._region_id(search.location)))

        # The captured public state identifies sort=1 as published.descending / Aktualität.
        parameters.append(("sort", NEWEST_FIRST_SORT))
        return MarketplaceSearchRequest(url=httpx.URL(path, params=parameters))

    @staticmethod
    def _decimal_parameter(value: Decimal) -> str:
        normalized = format(value, "f")
        if "." in normalized:
            normalized = normalized.rstrip("0").rstrip(".")
        return normalized

    def _region_id(self, location: str) -> str:
        key = _normalized_key(location)
        if key in _REGION_IDS:
            return _REGION_IDS[key]
        if location.strip() in _REGION_IDS.values():
            return location.strip()
        raise UnsupportedMarketplaceSearch(
            "Marketplace location must be an Austrian Bundesland, Wien, or a documented areaId"
        )

    def _category_path(self, category: object) -> str:
        key = _normalized_key(category)
        path = _CATEGORY_PATHS.get(key)
        if path is not None:
            return path
        raw = str(category).strip().casefold()
        if raw in _CATEGORY_PATHS.values():
            return raw
        # A deep, multi-segment category path (e.g. "apple/iphone-13-mini-5009987") is only
        # ever produced by our own URL importer parsing a real public Willhaben search URL
        # (see agent/app/willhaben/search_url_import.py) — never guessed from free text. A
        # single unverified segment (no "/") must still match the known top-level list above.
        if self._is_deep_category_path(raw):
            return raw
        raise UnsupportedMarketplaceSearch(
            "marketplace_category must be a supported name, ID, or SEO category segment"
        )

    @staticmethod
    def _is_deep_category_path(value: str) -> bool:
        if "/" not in value:
            return False
        segments = value.split("/")
        return len(segments) >= 2 and all(
            _CATEGORY_SEGMENT_RE.match(segment) for segment in segments
        )
