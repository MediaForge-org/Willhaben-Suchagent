"""Turn a public Willhaben Marketplace search URL into a precise SearchDefinition draft.

Strictly local, read-only URL parsing — no network request, no redirect following, no
fetch of the target. Only ``https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/...``
is ever accepted; everything else (other domains, other schemes, localhost, other Willhaben
sections) is rejected before any interpretation happens. This is what keeps the importer
from being usable as an SSRF/open-redirect primitive.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlsplit

from agent.app.willhaben.marketplace_search import (
    SUPPORTED_MARKETPLACE_CATEGORIES,
    region_name_for_area_id,
)

ALLOWED_HOSTS = ("www.willhaben.at", "willhaben.at")
MARKETPLACE_PATH_PREFIX = "/iad/kaufen-und-verkaufen/marktplatz"

_SEGMENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TRAILING_ID_RE = re.compile(r"-(\d+)$")

# Recognized as part of the semantic search intent.
_SUPPORTED_PARAMS = {"keyword", "PRICE_FROM", "PRICE_TO", "areaId"}
# Short-lived navigation/session bookkeeping the public site attaches to every link;
# never part of the persisted search.
_IGNORED_PARAMS = {"sfId", "rows", "isNavigation", "page", "NO_OF_HITS"}

_KNOWN_CATEGORY_LABELS = {path: label for label, path in SUPPORTED_MARKETPLACE_CATEGORIES}

# Cosmetic capitalization for a handful of brand names that a plain title-case would get
# wrong. This never affects the stored category_path (always the literal URL segment) or
# search matching — only the human-readable label shown in the extension.
_LABEL_WORD_OVERRIDES = {
    "iphone": "iPhone",
    "ipad": "iPad",
    "ipod": "iPod",
    "imac": "iMac",
    "macbook": "MacBook",
    "airpods": "AirPods",
    "playstation": "PlayStation",
}


class InvalidSearchUrlError(ValueError):
    """The given URL is not a supported, safe public Willhaben Marketplace search URL."""


@dataclass(frozen=True, slots=True)
class ImportedSearchDraft:
    category_path: str | None
    category_label: str | None
    query: str
    location: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    unsupported_filters: list[str] = field(default_factory=list)


def parse_marketplace_search_url(url: str) -> ImportedSearchDraft:
    if not isinstance(url, str) or len(url) > 2000:
        raise InvalidSearchUrlError("Die Willhaben-URL ist ungültig.")

    parts = urlsplit(url.strip())

    if parts.scheme != "https":
        raise InvalidSearchUrlError("Nur öffentliche https://-Willhaben-Links werden unterstützt.")
    if parts.username or parts.password:
        raise InvalidSearchUrlError("Die Willhaben-URL ist ungültig.")
    if parts.hostname not in ALLOWED_HOSTS:
        raise InvalidSearchUrlError(
            "Es werden ausschließlich Links von www.willhaben.at unterstützt."
        )
    if parts.port not in (None, 443):
        raise InvalidSearchUrlError("Die Willhaben-URL ist ungültig.")

    path = parts.path.rstrip("/")
    if path == MARKETPLACE_PATH_PREFIX:
        category_segment = ""
    elif path.startswith(MARKETPLACE_PATH_PREFIX + "/"):
        category_segment = path[len(MARKETPLACE_PATH_PREFIX) + 1 :]
    else:
        raise InvalidSearchUrlError("Nur Marktplatz-Suchlinks (…/marktplatz/…) werden unterstützt.")

    category_path: str | None = None
    category_label: str | None = None
    if category_segment:
        segments = category_segment.split("/")
        if not all(_SEGMENT_RE.match(segment) for segment in segments):
            raise InvalidSearchUrlError("Der Kategoriepfad in der Willhaben-URL ist ungültig.")
        category_path = "/".join(segments)
        category_label = _humanize_category_path(segments)

    unsupported_filters: list[str] = []
    query_text = ""
    location: str | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None

    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if name in _IGNORED_PARAMS or name.startswith("utm_"):
            continue
        if name == "sort":
            if value not in ("", "1"):
                unsupported_filters.append(
                    "Sortierung wird derzeit nicht übernommen; der Agent sortiert immer "
                    "nach Aktualität (Neueste zuerst)."
                )
            continue
        if name == "keyword":
            if value and not query_text:
                query_text = value
            continue
        if name == "PRICE_FROM":
            parsed = _parse_price(value)
            if parsed is None:
                unsupported_filters.append(
                    f"Filter 'PRICE_FROM={value}' konnte nicht gelesen werden."
                )
            else:
                price_min = parsed
            continue
        if name == "PRICE_TO":
            parsed = _parse_price(value)
            if parsed is None:
                unsupported_filters.append(
                    f"Filter 'PRICE_TO={value}' konnte nicht gelesen werden."
                )
            else:
                price_max = parsed
            continue
        if name == "areaId":
            resolved = region_name_for_area_id(value)
            if resolved is None:
                unsupported_filters.append(
                    f"Region-Filter 'areaId={value}' wird nicht unterstützt."
                )
            else:
                location = resolved
            continue
        if name not in _SUPPORTED_PARAMS:
            unsupported_filters.append(f"Filter '{name}' wird derzeit nicht unterstützt.")

    return ImportedSearchDraft(
        category_path=category_path,
        category_label=category_label,
        query=query_text,
        location=location,
        price_min=price_min,
        price_max=price_max,
        unsupported_filters=unsupported_filters,
    )


def _parse_price(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if parsed < 0:
        return None
    return parsed


def _humanize_category_path(segments: list[str]) -> str:
    full_path = "/".join(segments)
    known = _KNOWN_CATEGORY_LABELS.get(full_path)
    if known is not None:
        return known
    return " → ".join(_humanize_segment(segment) for segment in segments)


def _humanize_segment(segment: str) -> str:
    match = _TRAILING_ID_RE.search(segment)
    body = segment[: match.start()] if match else segment
    words = [word for word in body.split("-") if word]
    if not words:
        return segment
    return " ".join(_LABEL_WORD_OVERRIDES.get(word, word.capitalize()) for word in words)
