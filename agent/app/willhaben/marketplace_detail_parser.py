from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Any

from pydantic import ValidationError

from agent.app.core.exceptions import ParseError
from agent.app.core.models import ListingEnrichment, SellerType
from agent.app.willhaben.marketplace_parser import WillhabenMarketplaceParser


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


class WillhabenMarketplaceDetailParser:
    """Map the public Marketplace detail-page state to generic enrichment data."""

    def parse(self, html: str, *, expected_listing_id: str | None = None) -> ListingEnrichment:
        WillhabenMarketplaceParser.raise_for_challenge(html)
        if not html.strip():
            raise ParseError("Willhaben returned an empty detail response")

        parser = _NextDataParser()
        try:
            parser.feed(html)
            raw_data = "".join(parser.parts)
            if not raw_data:
                raise ParseError("Willhaben detail response does not contain __NEXT_DATA__")
            details = json.loads(raw_data)["props"]["pageProps"]["advertDetails"]
        except ParseError:
            raise
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise ParseError("Unexpected Willhaben detail page state") from error

        if not isinstance(details, dict) or details.get("verticalId") != 5:
            raise ParseError("Response is not a Willhaben Marketplace detail page")
        listing_id = self._text(details.get("id"))
        if expected_listing_id is not None and listing_id != expected_listing_id:
            raise ParseError("Willhaben detail page has an unexpected listing ID")

        attributes = self._attribute_map(details)
        tms = details.get("taggingData", {}).get("tmsDataValues", {}).get("tmsData", {})
        if not isinstance(tms, dict):
            tms = {}
        seller_type = self._seller_type(details, attributes, tms)

        try:
            return ListingEnrichment(
                title=self._title(details, tms),
                price=self._price(attributes, tms),
                image_url=self._image_url(details),
                location=self._location(details),
                seller_name=self._seller_name(details, seller_type),
                seller_type=seller_type,
                condition=self._condition(details),
                attributes=self._export_attributes(details),
            )
        except ValidationError as error:
            raise ParseError("Invalid public data on Willhaben detail page") from error

    @staticmethod
    def _text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = " ".join(value.split()).strip()
        return cleaned or None

    @classmethod
    def _attribute_map(cls, details: dict[str, Any]) -> dict[str, list[str]]:
        raw = details.get("attributes", {}).get("attribute", [])
        if not isinstance(raw, list):
            return {}
        mapped: dict[str, list[str]] = {}
        for item in raw:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            values = item.get("values", [])
            if isinstance(values, list):
                mapped[item["name"]] = [value for value in map(cls._text, values) if value]
        return mapped

    @staticmethod
    def _first(attributes: dict[str, list[str]], name: str) -> str | None:
        values = attributes.get(name, [])
        return values[0] if values else None

    @classmethod
    def _title(cls, details: dict[str, Any], tms: dict[str, Any]) -> str | None:
        title = cls._text(tms.get("ad_title"))
        if title:
            return title
        return cls._text(details.get("seoMetaData", {}).get("title"))

    @classmethod
    def _price(cls, attributes: dict[str, list[str]], tms: dict[str, Any]) -> Decimal | None:
        raw = cls._first(attributes, "PRICE/AMOUNT") or cls._first(attributes, "PRICE")
        raw = raw or cls._text(tms.get("exact_price"))
        if raw is None:
            return None
        try:
            normalized = raw.replace(" ", "")
            if "," in normalized:
                normalized = normalized.replace(".", "").replace(",", ".")
            price = Decimal(normalized)
        except InvalidOperation:
            return None
        return price if price >= 0 else None

    @classmethod
    def _seller_type(
        cls,
        details: dict[str, Any],
        attributes: dict[str, list[str]],
        tms: dict[str, Any],
    ) -> SellerType | None:
        profile_value = details.get("sellerProfileUserData", {}).get("private")
        if isinstance(profile_value, bool):
            return SellerType.PRIVATE if profile_value else SellerType.COMMERCIAL
        raw = cls._first(attributes, "ISPRIVATE") or cls._text(tms.get("is_private"))
        if raw is None:
            return None
        normalized = raw.casefold()
        if normalized in {"1", "true"}:
            return SellerType.PRIVATE
        if normalized in {"0", "false"}:
            return SellerType.COMMERCIAL
        return None

    @classmethod
    def _seller_name(
        cls,
        details: dict[str, Any],
        seller_type: SellerType | None,
    ) -> str | None:
        profile = details.get("sellerProfileUserData", {})
        organisation = details.get("organisationDetails", {})
        profile_name = cls._text(profile.get("name")) if isinstance(profile, dict) else None
        organisation_name = (
            cls._text(organisation.get("orgName")) if isinstance(organisation, dict) else None
        )
        if seller_type is SellerType.COMMERCIAL:
            return organisation_name or profile_name
        return profile_name or organisation_name

    @classmethod
    def _location(cls, details: dict[str, Any]) -> str | None:
        profile = details.get("sellerProfileUserData", {})
        if isinstance(profile, dict):
            location = cls._text(profile.get("location"))
            if location:
                return location
        address = details.get("advertAddressDetails", {})
        if not isinstance(address, dict):
            return None
        address_lines = address.get("addressLines", {})
        if isinstance(address_lines, dict):
            location = cls._text(address_lines.get("value"))
            if location:
                return location
        return cls._text(address.get("postalName")) or cls._text(address.get("district"))

    @classmethod
    def _condition(cls, details: dict[str, Any]) -> str | None:
        information = details.get("attributeInformation", [])
        if not isinstance(information, list):
            return None
        for item in information:
            if not isinstance(item, dict):
                continue
            element = item.get("treeAttributeElement", {})
            if not isinstance(element, dict):
                continue
            identifiers = (cls._text(element.get("code")), cls._text(element.get("label")))
            if not any(value and value.casefold() == "zustand" for value in identifiers):
                continue
            values = item.get("values", [])
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict):
                        label = cls._text(value.get("label"))
                        if label:
                            return label
        return None

    @staticmethod
    def _image_url(details: dict[str, Any]) -> str | None:
        images = details.get("advertImageList", {}).get("advertImage", [])
        if not isinstance(images, list) or not images or not isinstance(images[0], dict):
            return None
        for key in ("mainImageUrl", "referenceImageUrl", "thumbnailImageUrl"):
            value = images[0].get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @classmethod
    def _export_attributes(cls, details: dict[str, Any]) -> dict[str, Any]:
        exported: dict[str, Any] = {}
        dates = {
            "created_at": details.get("createdDate"),
            "published_at": details.get("publishedDate"),
            "changed_at": details.get("changedDate"),
        }
        for target, value in dates.items():
            cleaned = cls._text(value)
            if cleaned:
                exported[target] = cleaned

        breadcrumbs = details.get("breadcrumbs", [])
        if isinstance(breadcrumbs, list):
            categories = [
                cleaned
                for item in breadcrumbs
                if isinstance(item, dict)
                if (cleaned := cls._text(item.get("displayName")))
            ]
            if categories:
                exported["category_path"] = categories

        public_attributes: dict[str, list[str]] = {}
        information = details.get("attributeInformation", [])
        if isinstance(information, list):
            for item in information:
                if not isinstance(item, dict):
                    continue
                element = item.get("treeAttributeElement", {})
                label = cls._text(element.get("label")) if isinstance(element, dict) else None
                values = item.get("values", [])
                if label and isinstance(values, list):
                    value_labels = [
                        cleaned
                        for value in values
                        if isinstance(value, dict)
                        if (cleaned := cls._text(value.get("label")))
                    ]
                    if value_labels:
                        public_attributes[label] = value_labels
        if public_attributes:
            exported["public_attributes"] = public_attributes
        return exported
