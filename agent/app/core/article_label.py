from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

FALLBACK_ARTICLE_LABEL = "der Artikel"

_BRAND_KEYS = ("brand", "marke", "hersteller", "manufacturer")
_MODEL_KEYS = ("model", "modell", "modelname", "modellname")
_PRODUCT_KEYS = (
    "article_label",
    "artikelbezeichnung",
    "product_name",
    "productname",
    "produktname",
    "produkt",
)
_TITLE_SEPARATOR = re.compile(r"\s+(?:\||-|–|—)\s+|\s*\|\s*")
_IPHONE_WITH_STORAGE = re.compile(
    r"^(iPhone\s+\d+(?:\s+(?:Pro|Plus|Max|Mini)){0,2}\s+\d+\s*(?:GB|TB))\b",
    re.IGNORECASE,
)
_UNRELIABLE = re.compile(
    r"^(?:verkaufe|zu verkaufen|angebot|diverses|sonstiges|artikel|ware|produkt)$",
    re.IGNORECASE,
)


def derive_article_label(title: str | None, attributes: Mapping[str, Any] | None) -> str:
    """Derive a conservative product label without inventing missing information."""

    flattened = _flatten_attributes(attributes or {})
    product = _first_value(flattened, _PRODUCT_KEYS)
    brand = _first_value(flattened, _BRAND_KEYS)
    model = _first_value(flattened, _MODEL_KEYS)

    structured = _combine_distinct(brand, model)
    if product:
        structured = _combine_distinct(structured, product)
    if structured and _is_reliable(structured):
        return structured[:500]

    cleaned = _clean_title(title)
    if cleaned and _is_reliable(cleaned):
        return cleaned[:500]
    return FALLBACK_ARTICLE_LABEL


def _flatten_attributes(attributes: Mapping[str, Any]) -> dict[str, list[str]]:
    flattened: dict[str, list[str]] = {}

    def visit(value: Any, key: str | None = None) -> None:
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                visit(nested_value, str(nested_key))
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif key is not None and value is not None and not isinstance(value, bool):
            text = " ".join(str(value).split()).strip()
            if text:
                normalized = re.sub(r"[^a-z0-9]+", "", key.casefold())
                flattened.setdefault(normalized, []).append(text)

    visit(attributes)
    return flattened


def _first_value(values: dict[str, list[str]], keys: Sequence[str]) -> str | None:
    normalized_keys = [re.sub(r"[^a-z0-9]+", "", key.casefold()) for key in keys]
    for key in normalized_keys:
        candidates = values.get(key)
        if candidates:
            return candidates[0]
    return None


def _combine_distinct(first: str | None, second: str | None) -> str | None:
    if not first:
        return second
    if not second:
        return first
    if second.casefold() in first.casefold():
        return first
    if first.casefold() in second.casefold():
        return second
    return f"{first} {second}"


def _clean_title(title: str | None) -> str | None:
    if not title:
        return None
    cleaned = " ".join(title.split()).strip(" -|–—,;:")
    if not cleaned:
        return None
    candidate = _TITLE_SEPARATOR.split(cleaned, maxsplit=1)[0].strip(" -|–—,;:")
    iphone = _IPHONE_WITH_STORAGE.match(candidate)
    if iphone:
        candidate = iphone.group(1)
    return candidate or None


def _is_reliable(value: str) -> bool:
    return (
        len(value) >= 2
        and bool(re.search(r"[A-Za-zÄÖÜäöü0-9]", value))
        and not _UNRELIABLE.fullmatch(value)
    )
