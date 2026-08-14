from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

FALLBACK_ARTICLE_LABEL = "Artikel"
FALLBACK_ARTICLE_PHRASE = "der Artikel"

# Central, deliberately conservative vocabulary. Keys are product types (including
# common category plurals); values are the German definite articles used in messages.
PRODUCT_TYPE_ARTICLES: dict[str, str] = {
    "selfie stick": "der",
    "selfie-stick": "der",
    "stick": "der",
    "handyhülle": "die",
    "handyhüllen": "die",
    "hülle": "die",
    "hüllen": "die",
    "tasche": "die",
    "taschen": "die",
    "tastatur": "die",
    "tastaturen": "die",
    "maus": "die",
    "mäuse": "die",
    "kamera": "die",
    "kameras": "die",
    "konsole": "die",
    "konsolen": "die",
    "smartphone": "das",
    "smartphones": "das",
    "handy": "das",
    "handys": "das",
    "notebook": "das",
    "notebooks": "das",
    "laptop": "der",
    "laptops": "der",
    "fernseher": "der",
    "monitor": "der",
    "monitore": "der",
    "kopfhörer": "der",
    "drucker": "der",
    "controller": "der",
    "fernbedienung": "die",
    "fernbedienungen": "die",
    "tablet": "das",
    "tablets": "das",
}

# Product families with an unambiguous conventional article. These are considered
# only after explicit types, title types and category information.
KNOWN_PRODUCT_FAMILY_ARTICLES: dict[str, str] = {
    "iphone": "das",
    "thinkpad": "das",
}

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
_PRODUCT_TYPE_KEYS = (
    "product_type",
    "producttype",
    "produkttyp",
    "produktart",
    "artikelart",
    "warentyp",
    "warenart",
    "gerätetyp",
    "typ",
    "type",
)
_CATEGORY_KEYS = (
    "category_path",
    "categorypath",
    "category_level_max",
    "categorylevelmax",
    "category_name",
    "categoryname",
    "kategorie",
    "unterkategorie",
)
_TITLE_SEPARATOR = re.compile(r"\s+(?:\||-|–|—)\s+|\s*\|\s*")
_TRAILING_TITLE_QUALIFIER = re.compile(
    r"(?:\s*[,;]\s*|\s+)"
    r"(?:wie\s+neu|neuwertig|top[- ]?zustand|sehr\s+guter\s+zustand|"
    r"guter\s+zustand|neu|rechnung|versand)\s*$",
    re.IGNORECASE,
)
_TRAILING_ACCESSORY = re.compile(
    r"\s+\+\s+(?:zubeh[oö]r|extras?)(?:\s*[,;]\s*)?$",
    re.IGNORECASE,
)
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
    # A brand by itself is not a natural product name. Prefer the informative title
    # unless a structured model or product attribute adds an actual identity.
    if (model or product) and structured and _is_reliable(structured):
        return structured[:500]

    cleaned = _clean_title(title)
    if cleaned and _is_reliable(cleaned):
        return cleaned[:500]
    return FALLBACK_ARTICLE_LABEL


def derive_article_phrase(
    article_label: str,
    title: str | None,
    attributes: Mapping[str, Any] | None,
) -> str:
    """Build a deterministic German noun phrase or use the neutral safe fallback."""

    flattened = _flatten_attributes(attributes or {})

    # 1. Explicit structured product type.
    article = _article_for_values(_values_for_keys(flattened, _PRODUCT_TYPE_KEYS))
    # 2. Unambiguous product type in the cleaned product title/label.
    if article is None:
        article = _article_for_values((article_label, _clean_title(title) or ""))
    # 3. Category and subcategory information.
    if article is None:
        article = _article_for_values(_values_for_keys(flattened, _CATEGORY_KEYS))
    # 4. Conservative known product-family assignment.
    if article is None:
        article = _article_for_values(
            (article_label, _clean_title(title) or ""),
            vocabulary=KNOWN_PRODUCT_FAMILY_ARTICLES,
        )

    clean_label = " ".join(article_label.split()).strip()
    if not _is_reliable(clean_label):
        return FALLBACK_ARTICLE_PHRASE
    if article is None:
        return clean_label[:500]
    return f"{article} {clean_label}"[:504]


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
                normalized = _normalize_key(key)
                flattened.setdefault(normalized, []).append(text)

    visit(attributes)
    return flattened


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", "", value.casefold())


def _values_for_keys(values: dict[str, list[str]], keys: Sequence[str]) -> Iterable[str]:
    for key in keys:
        yield from values.get(_normalize_key(key), ())


def _first_value(values: dict[str, list[str]], keys: Sequence[str]) -> str | None:
    return next(iter(_values_for_keys(values, keys)), None)


def _article_for_values(
    values: Iterable[str],
    *,
    vocabulary: Mapping[str, str] = PRODUCT_TYPE_ARTICLES,
) -> str | None:
    # The earliest recognized term is the product head. At the same position the
    # most specific term wins (for example Selfie Stick before Stick).
    for value in values:
        normalized = value.casefold()
        matches: list[tuple[int, int, str]] = []
        for term in vocabulary:
            if match := re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized):
                matches.append((match.start(), -len(term), term))
        if matches:
            _, _, term = min(matches)
            return vocabulary[term]
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
    previous = None
    while candidate and candidate != previous:
        previous = candidate
        candidate = _TRAILING_TITLE_QUALIFIER.sub("", candidate).strip(" -|–—,;:")
        candidate = _TRAILING_ACCESSORY.sub("", candidate).strip(" -|–—,;:")
    candidate = re.sub(r"\bx(?=\d)", "X", candidate, flags=re.IGNORECASE)
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
