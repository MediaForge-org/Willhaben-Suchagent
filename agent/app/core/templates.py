from __future__ import annotations

import re
from decimal import Decimal

from agent.app.core.article_label import FALLBACK_ARTICLE_LABEL
from agent.app.core.models import Listing

DEFAULT_TEMPLATE_NAME = "Standard"
DEFAULT_TEMPLATE_BODY = """Hallo [Name],

ist [Artikel] noch verfügbar?
Ich hätte Interesse.

Lg"""

SUPPORTED_PLACEHOLDERS = {
    "[Name]": "Verkäufer/Anbieter",
    "[Artikel]": "kurze Artikelbezeichnung",
    "[Preis]": "Preis",
    "[Ort]": "Standort",
    "[Zustand]": "Zustand",
    "[URL]": "Inserat-Link",
}
_PLACEHOLDER_PATTERN = re.compile(r"\[[^\[\]\n]+\]")


def validate_template_body(body: str) -> None:
    unknown = sorted(set(_PLACEHOLDER_PATTERN.findall(body)) - SUPPORTED_PLACEHOLDERS.keys())
    if unknown:
        raise ValueError(f"Nicht unterstützte Platzhalter: {', '.join(unknown)}")


def render_template(body: str, listing: Listing) -> str:
    """Render all supported placeholders and normalize gaps left by missing values."""

    validate_template_body(body)
    values = {
        "[Name]": _clean(listing.seller_name),
        "[Artikel]": _clean(listing.article_label) or FALLBACK_ARTICLE_LABEL,
        "[Preis]": _format_price(listing.price),
        "[Ort]": _clean(listing.location),
        "[Zustand]": _clean(listing.condition),
        "[URL]": str(listing.url),
    }
    rendered_lines: list[str] = []
    for line in body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        missing_on_line = [
            placeholder
            for placeholder, value in values.items()
            if not value and placeholder in line
        ]
        rendered_line = line
        for placeholder, value in values.items():
            rendered_line = rendered_line.replace(placeholder, value)
        if missing_on_line:
            rendered_line = _normalize_removed_placeholder_artifacts(rendered_line)
        if missing_on_line and re.fullmatch(r"\s*[\wÄÖÜäöüß /-]+\s*[:\-–—]\s*", rendered_line):
            rendered_line = ""
        rendered_lines.append(rendered_line)
    return _normalize_missing_values("\n".join(rendered_lines))


def _clean(value: str | None) -> str:
    return " ".join(value.split()).strip() if value else ""


def _format_price(price: Decimal | None) -> str:
    if price is None:
        return ""
    formatted = format(price, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return f"{formatted} €"


def _normalize_missing_values(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)
        if re.fullmatch(r"[,.;:!?\-–—]+", line):
            line = ""
        if line or (lines and lines[-1] != ""):
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _normalize_removed_placeholder_artifacts(line: str) -> str:
    """Clean spacing and punctuation runs left by one or more empty placeholders."""

    normalized = re.sub(r"[ \t]+", " ", line)
    normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
    normalized = re.sub(
        r"([,.;:!?])(?:\s*[,.;:!?])+",
        lambda match: match.group(0).rstrip()[-1],
        normalized,
    )
    return normalized
