from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from pydantic import ValidationError

from agent.app.core.exceptions import ChallengeDetectedError, ParseError
from agent.app.core.models import Listing, SearchCategory

logger = logging.getLogger(__name__)

_PUBLIC_BASE_URL = "https://www.willhaben.at/iad/"
_CHALLENGE_MARKERS = (
    "captcha",
    "cf-chl",
    "g-recaptcha",
    "hcaptcha",
    "are you a robot",
    "bot protection",
    "just a moment...",
    "verify you are human",
    "unusual traffic",
    "automatisierte anfragen",
    "/challenge-platform/",
    "<title>access denied",
    "<title>security challenge",
)
_EXPORTED_ATTRIBUTES = {
    "ADTYPE_ID": "ad_type_id",
    "CHANGED_String": "changed_at",
    "DISTRICT": "district",
    "ISPRIVATE": "is_private",
    "POSTCODE": "postcode",
    "PRODUCT_ID": "product_id",
    "PUBLISHED_String": "published_at",
    "STATE": "state",
    "categorytreeids": "marketplace_category_ids",
    "p2penabled": "paylivery_enabled",
}


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capturing = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._capturing = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._capturing:
            self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self.parts.append(data)


class WillhabenMarketplaceParser:
    """Parse public Next.js page state and map Marketplace adverts to Listings."""

    def parse(self, html: str) -> list[Listing]:
        self.raise_for_challenge(html)
        if not html.strip():
            raise ParseError("Willhaben returned an empty response")

        parser = _NextDataParser()
        try:
            parser.feed(html)
            raw_data = "".join(parser.parts)
            if not raw_data:
                raise ParseError("Willhaben response does not contain __NEXT_DATA__")
            page_state = json.loads(raw_data)
            search_result = page_state["props"]["pageProps"]["searchResult"]
        except ParseError:
            raise
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ParseError("Unexpected Willhaben page state") from error

        if not isinstance(search_result, dict) or search_result.get("verticalId") != 5:
            raise ParseError("Response is not a Willhaben Marketplace search result")

        raw_list = search_result.get("advertSummaryList")
        if raw_list is None and search_result.get("rowsReturned") == 0:
            return []
        if not isinstance(raw_list, dict):
            raise ParseError("Marketplace result has no advert summary list")
        adverts = raw_list.get("advertSummary")
        if adverts is None:
            adverts = []
        if not isinstance(adverts, list):
            raise ParseError("Marketplace advert summary is not a list")

        listings: list[Listing] = []
        seen_ids: set[str] = set()
        for advert in adverts:
            try:
                listing = self._map_advert(advert)
            except (KeyError, TypeError, ValueError, ValidationError) as error:
                listing_id = advert.get("id") if isinstance(advert, dict) else None
                logger.warning(
                    "marketplace_listing_parse_failed provider_listing_id=%s error_type=%s",
                    listing_id,
                    type(error).__name__,
                )
                continue
            if listing.provider_listing_id not in seen_ids:
                seen_ids.add(listing.provider_listing_id)
                listings.append(listing)

        if adverts and not listings:
            raise ParseError("No Marketplace advert could be mapped")
        return listings

    @staticmethod
    def raise_for_challenge(html: str) -> None:
        sample = html[:250_000].casefold()
        if any(marker in sample for marker in _CHALLENGE_MARKERS):
            raise ChallengeDetectedError("Willhaben challenge page detected")

    def _map_advert(self, advert: Any) -> Listing:
        if not isinstance(advert, dict):
            raise TypeError("Advert must be an object")
        attributes = self._attribute_map(advert)
        provider_listing_id = str(advert["id"]).strip()
        if not provider_listing_id:
            raise ValueError("Advert ID is empty")

        title = self._first_attribute(attributes, "HEADING")
        if title is None:
            description = advert.get("description")
            title = str(description).strip() if description else None
        if not title:
            raise ValueError("Advert title is empty")

        return Listing(
            provider_listing_id=provider_listing_id,
            title=title[:1000],
            price=self._price(attributes),
            url=self._listing_url(advert, attributes),
            image_url=self._image_url(advert),
            category=SearchCategory.MARKETPLACE,
            location=self._first_attribute(attributes, "LOCATION"),
            attributes=self._export_attributes(attributes),
        )

    @staticmethod
    def _attribute_map(advert: dict[str, Any]) -> dict[str, list[str]]:
        raw_attributes = advert.get("attributes", {}).get("attribute", [])
        if not isinstance(raw_attributes, list):
            return {}
        mapped: dict[str, list[str]] = {}
        for attribute in raw_attributes:
            if not isinstance(attribute, dict) or not isinstance(attribute.get("name"), str):
                continue
            values = attribute.get("values")
            if isinstance(values, list):
                mapped[attribute["name"]] = [str(value) for value in values]
        return mapped

    @staticmethod
    def _first_attribute(attributes: dict[str, list[str]], name: str) -> str | None:
        values = attributes.get(name, [])
        if not values:
            return None
        value = values[0].strip()
        return value or None

    def _price(self, attributes: dict[str, list[str]]) -> Decimal | None:
        raw_price = self._first_attribute(attributes, "PRICE/AMOUNT")
        if raw_price is None:
            raw_price = self._first_attribute(attributes, "PRICE")
        if raw_price is None:
            return None
        try:
            price = Decimal(raw_price.replace(",", "."))
        except InvalidOperation:
            return None
        return price if price >= 0 else None

    def _listing_url(self, advert: dict[str, Any], attributes: dict[str, list[str]]) -> str:
        seo_path = self._first_attribute(attributes, "SEO_URL")
        if seo_path:
            return urljoin(_PUBLIC_BASE_URL, seo_path.lstrip("/"))

        links = advert.get("contextLinkList", {}).get("contextLink", [])
        if isinstance(links, list):
            for link in links:
                if isinstance(link, dict) and link.get("id") == "iadShareLink":
                    uri = link.get("uri")
                    if isinstance(uri, str) and uri:
                        return uri
        raise ValueError("Advert has no public detail URL")

    @staticmethod
    def _image_url(advert: dict[str, Any]) -> str | None:
        images = advert.get("advertImageList", {}).get("advertImage", [])
        if not isinstance(images, list) or not images or not isinstance(images[0], dict):
            return None
        image = images[0]
        for key in ("mainImageUrl", "referenceImageUrl", "thumbnailImageUrl"):
            value = image.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    def _export_attributes(self, attributes: dict[str, list[str]]) -> dict[str, Any]:
        exported: dict[str, Any] = {}
        for source_name, target_name in _EXPORTED_ATTRIBUTES.items():
            value = self._first_attribute(attributes, source_name)
            if value is None:
                continue
            if target_name in {"is_private", "paylivery_enabled"}:
                exported[target_name] = value.casefold() in {"1", "true"}
            elif target_name == "marketplace_category_ids":
                exported[target_name] = [item for item in value.split(";") if item]
            else:
                exported[target_name] = value
        return exported
