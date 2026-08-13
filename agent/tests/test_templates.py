import sqlite3
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from agent.app.core.article_label import FALLBACK_ARTICLE_LABEL, derive_article_label
from agent.app.core.models import SearchCategory
from agent.app.core.templates import DEFAULT_TEMPLATE_BODY, render_template
from agent.app.storage.database import Database
from agent.app.willhaben.fake_provider import FakeListingProvider


def test_article_label_prefers_structured_brand_model_and_product() -> None:
    assert (
        derive_article_label(
            "Unzuverlässiger Titel mit Werbung",
            {"public_attributes": {"Marke": ["Sony"], "Modell": ["WH-1000XM5"]}},
        )
        == "Sony WH-1000XM5"
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        (
            "Sony WH-1000XM5 - Premium Noise Cancelling Kopfhörer in Top-Zustand",
            "Sony WH-1000XM5",
        ),
        ("Lenovo ThinkPad T14 G3 | i7 32GB Touch | Garantie & Rechnung", "Lenovo ThinkPad T14 G3"),
        ("iPhone 15 Pro 256GB Titan Natur - wie neu mit Rechnung", "iPhone 15 Pro 256GB"),
    ],
)
def test_article_label_conservatively_cleans_title(title: str, expected: str) -> None:
    assert derive_article_label(title, {}) == expected


@pytest.mark.parametrize("title", [None, "", "Sonstiges", "Verkaufe"])
def test_article_label_uses_neutral_fallback(title: str | None) -> None:
    assert derive_article_label(title, {}) == FALLBACK_ARTICLE_LABEL


def test_template_replaces_every_supported_placeholder(listing_factory) -> None:
    listing = listing_factory(
        title="Sony WH-1000XM5 - Top Zustand",
        article_label="Sony WH-1000XM5",
        price=Decimal("180"),
        seller_name="Markus",
        location="Wien",
        condition="Neuwertig",
        url="https://www.willhaben.at/iad/object/123",
    )
    rendered = render_template(
        "[Name]|[Artikel]|[Preis]|[Ort]|[Zustand]|[URL]",
        listing,
    )
    assert rendered == (
        "Markus|Sony WH-1000XM5|180 €|Wien|Neuwertig|https://www.willhaben.at/iad/object/123"
    )


def test_missing_values_are_normalized_without_raw_placeholders(listing_factory) -> None:
    listing = listing_factory(
        title="Sonstiges",
        article_label=FALLBACK_ARTICLE_LABEL,
        seller_name=None,
        price=None,
        location=None,
        condition=None,
    )
    rendered = render_template(
        DEFAULT_TEMPLATE_BODY + "\nPreis: [Preis]\nOrt: [Ort]\nZustand: [Zustand]",
        listing,
    )
    assert rendered == "Hallo,\n\nist der Artikel noch verfügbar?\nIch hätte Interesse.\n\nLg"
    assert not any(value in rendered for value in ("None", "null", "undefined", "["))


def test_greeting_with_present_name_keeps_name_and_comma(listing_factory) -> None:
    listing = listing_factory(seller_name="Markus")

    assert render_template("Hallo [Name],", listing) == "Hallo Markus,"


def test_greeting_without_name_keeps_only_one_valid_comma(listing_factory) -> None:
    listing = listing_factory(seller_name=None)

    assert render_template("Hallo [Name],", listing) == "Hallo,"


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("Hallo [Name],.", "Hallo."),
        ("Hallo [Name]..", "Hallo."),
        ("Hallo  [Name]  Welt", "Hallo Welt"),
        ("Hallo [Name] , !", "Hallo!"),
    ],
)
def test_missing_placeholder_leaves_no_punctuation_or_spacing_artifacts(
    listing_factory,
    template: str,
    expected: str,
) -> None:
    listing = listing_factory(seller_name=None)
    rendered = render_template(template, listing)

    assert rendered == expected
    assert ",." not in rendered
    assert ".." not in rendered
    assert "  " not in rendered


def test_template_normalization_preserves_meaningful_blank_lines(listing_factory) -> None:
    listing = listing_factory(seller_name=None, article_label="Sony WH-1000XM5")

    assert render_template(DEFAULT_TEMPLATE_BODY, listing) == (
        "Hallo,\n\nist Sony WH-1000XM5 noch verfügbar?\nIch hätte Interesse.\n\nLg"
    )


@pytest.mark.asyncio
async def test_template_crud_default_and_used_template_deletion(
    api_client: httpx.AsyncClient,
) -> None:
    initial = (await api_client.get("/api/v1/templates")).json()
    assert len(initial) == 1
    assert initial[0]["name"] == "Standard"
    assert initial[0]["body"] == DEFAULT_TEMPLATE_BODY

    created_response = await api_client.post(
        "/api/v1/templates", json={"name": "Kaufinteresse", "body": "Hallo [Name]!"}
    )
    assert created_response.status_code == 201
    template_id = created_response.json()["id"]
    assert (await api_client.get(f"/api/v1/templates/{template_id}")).status_code == 200
    patched = await api_client.patch(
        f"/api/v1/templates/{template_id}", json={"body": "Ist [Artikel] verfügbar?"}
    )
    assert patched.status_code == 200

    search = await api_client.post(
        "/api/v1/searches",
        json={
            "name": "ThinkPad",
            "category": "marketplace",
            "query": "ThinkPad",
            "default_template_id": template_id,
        },
    )
    assert search.status_code == 201
    search_id = search.json()["id"]
    assert search.json()["default_template_id"] == template_id

    assert (await api_client.delete(f"/api/v1/templates/{template_id}")).status_code == 204
    assert (await api_client.get(f"/api/v1/searches/{search_id}")).json()[
        "default_template_id"
    ] is None


@pytest.mark.asyncio
async def test_template_api_rejects_unknown_placeholder(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/templates", json={"name": "Ungültig", "body": "Hallo [Unbekannt]"}
    )
    assert response.status_code == 422
    assert "Nicht unterstützte Platzhalter" in response.json()["detail"]


@pytest.mark.asyncio
async def test_render_endpoint_uses_real_persisted_listing(
    api_client: httpx.AsyncClient,
    test_app: FastAPI,
    provider: FakeListingProvider,
    listing_factory,
) -> None:
    search_response = await api_client.post(
        "/api/v1/searches",
        json={"name": "Audio", "category": "marketplace", "query": "Sony"},
    )
    search_id = search_response.json()["id"]
    provider.set_results(
        search_id,
        [
            listing_factory(
                "render-listing",
                category=SearchCategory.MARKETPLACE,
                title="Sony WH-1000XM5 - Top Zustand",
                seller_name="Markus",
                url="https://www.willhaben.at/iad/object/render-listing",
            )
        ],
    )
    await test_app.state.scheduler.run_cycle()
    listing = (await api_client.get("/api/v1/listings/recent")).json()[0]
    template_id = (await api_client.get("/api/v1/templates")).json()[0]["id"]

    rendered = await api_client.post(
        f"/api/v1/templates/{template_id}/render",
        json={"listing_id": listing["listing_id"]},
    )
    assert rendered.status_code == 200
    assert rendered.json()["rendered_text"].startswith("Hallo Markus,\n\nist Sony WH-1000XM5")


@pytest.mark.asyncio
async def test_m4_migration_preserves_m31_search_baseline_and_listing(tmp_path: Path) -> None:
    path = tmp_path / "m31.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, category TEXT NOT NULL,
                query_json TEXT NOT NULL, enabled INTEGER NOT NULL,
                baseline_initialized INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_checked_at TEXT,
                last_success_at TEXT, consecutive_errors INTEGER NOT NULL
            );
            CREATE TABLE listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, provider_listing_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL, price TEXT, url TEXT NOT NULL, image_url TEXT,
                category TEXT NOT NULL,
                location TEXT, seller_name TEXT, seller_type TEXT, condition TEXT,
                enrichment_status TEXT NOT NULL, attributes_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO searches VALUES (1, 'Alt', 'marketplace', ?, 1, 1, ?, ?, ?, ?, 0)",
            (
                '{"category_filters":{},"location":null,"price_max":null,"price_min":null,"query":"Alt"}',
            )
            + ("2026-01-01T00:00:00+00:00",) * 4,
        )
        connection.execute(
            "INSERT INTO listings VALUES (1, 'old', 'Altes Gerät - gut', NULL, ?, NULL, "
            "'marketplace', 'Wien', NULL, NULL, NULL, 'partial', '{}', ?, ?)",
            ("https://example.test/old",) + ("2026-01-01T00:00:00+00:00",) * 2,
        )

    database = Database(path)
    await database.initialize()
    search = await database.get_search(1)
    listing = await database.get_listing(1)
    assert search is not None and search.baseline_initialized is True
    assert search.default_template_id is None
    assert listing is not None and listing.title == "Altes Gerät - gut"
    assert listing.article_label == "Altes Gerät"
    assert len(await database.list_templates()) == 1
