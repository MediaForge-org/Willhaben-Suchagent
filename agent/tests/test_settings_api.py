from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from agent.app.core.config import Settings
from agent.app.main import create_app
from agent.app.willhaben.fake_provider import FakeListingProvider


@pytest.fixture
def real_settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        secret_store_path=tmp_path / "secrets.json",
        app_environment="test",
        scheduler_enabled=False,
        desktop_sound_enabled=False,
        ntfy_enabled=False,
        ntfy_topic=None,
        ntfy_token=None,
        discord_enabled=False,
        discord_webhook_url=None,
        email_enabled=False,
        email_smtp_host=None,
        email_smtp_password=None,
        email_from_address=None,
        email_to_address=None,
    )


@pytest_asyncio.fixture
async def real_app(real_settings: Settings) -> AsyncIterator[FastAPI]:
    app = create_app(real_settings, FakeListingProvider())
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def real_api_client(real_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=real_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# -- Global settings (SMTP sender + timeouts only) --------------------------------------


@pytest.mark.asyncio
async def test_get_settings_never_returns_secrets(real_api_client: httpx.AsyncClient) -> None:
    response = await real_api_client.get("/api/v1/settings")
    assert response.status_code == 200
    notifications = response.json()["notifications"]
    assert notifications["email_smtp_password_configured"] is False
    assert "email_smtp_password" not in notifications


@pytest.mark.asyncio
async def test_smtp_sender_settings_can_be_saved_and_password_stays_masked(
    real_api_client: httpx.AsyncClient,
) -> None:
    response = await real_api_client.patch(
        "/api/v1/settings/notifications",
        json={
            "email_smtp_host": "smtp.example.test",
            "email_smtp_port": 587,
            "email_smtp_username": "agent@example.test",
            "email_smtp_password": "hunter2",
            "email_from_address": "agent@example.test",
            "email_encryption": "starttls",
        },
    )
    assert response.status_code == 200
    assert "hunter2" not in response.text
    body = response.json()
    assert body["email_smtp_password_configured"] is True
    assert body["email_smtp_host"] == "smtp.example.test"

    reloaded = await real_api_client.get("/api/v1/settings")
    assert "hunter2" not in reloaded.text
    assert reloaded.json()["notifications"]["email_smtp_password_configured"] is True


@pytest.mark.asyncio
async def test_smtp_settings_reject_invalid_encryption(
    real_api_client: httpx.AsyncClient,
) -> None:
    response = await real_api_client.patch(
        "/api/v1/settings/notifications",
        json={"email_encryption": "carrier-pigeon"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_settings_requires_at_least_one_field(
    real_api_client: httpx.AsyncClient,
) -> None:
    response = await real_api_client.patch("/api/v1/settings/notifications", json={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_saving_one_field_does_not_blank_out_existing_smtp_password(
    real_api_client: httpx.AsyncClient,
) -> None:
    await real_api_client.patch(
        "/api/v1/settings/notifications",
        json={"email_smtp_host": "smtp.example.test", "email_smtp_password": "kept-secret"},
    )
    response = await real_api_client.patch(
        "/api/v1/settings/notifications",
        json={"ntfy_timeout_seconds": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email_smtp_password_configured"] is True
    assert body["email_smtp_host"] == "smtp.example.test"
    assert body["ntfy_timeout_seconds"] == 5


# -- Notification target CRUD ------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_ntfy_target_never_returns_topic_or_token(
    real_api_client: httpx.AsyncClient,
) -> None:
    response = await real_api_client.post(
        "/api/v1/notification-targets",
        json={
            "type": "ntfy",
            "name": "Maxim iPhone",
            "base_url": "https://ntfy.sh",
            "topic": "super-secret-topic",
            "token": "tk_abc123",
        },
    )
    assert response.status_code == 201
    assert "super-secret-topic" not in response.text
    assert "tk_abc123" not in response.text
    body = response.json()
    assert body["type"] == "ntfy"
    assert body["name"] == "Maxim iPhone"
    assert body["configured"] is True
    assert body["ntfy_topic_configured"] is True
    assert body["ntfy_token_configured"] is True


@pytest.mark.asyncio
async def test_create_discord_target_validates_webhook_url(
    real_api_client: httpx.AsyncClient,
) -> None:
    rejected = await real_api_client.post(
        "/api/v1/notification-targets",
        json={"type": "discord", "name": "Papa", "webhook_url": "https://example.com/fake"},
    )
    assert rejected.status_code == 422
    assert "example.com" not in rejected.text

    accepted = await real_api_client.post(
        "/api/v1/notification-targets",
        json={
            "type": "discord",
            "name": "Papa – Willhaben",
            "webhook_url": "https://discord.com/api/webhooks/123456789012345678/aValidToken",
        },
    )
    assert accepted.status_code == 201
    assert "aValidToken" not in accepted.text
    body = accepted.json()
    assert body["discord_webhook_configured"] is True
    assert body["configured"] is True


@pytest.mark.asyncio
async def test_create_email_target_masks_address_but_shows_it_unmasked_in_email_address(
    real_api_client: httpx.AsyncClient,
) -> None:
    response = await real_api_client.post(
        "/api/v1/notification-targets",
        json={"type": "email", "name": "Papa", "email_address": "papa@gmail.com"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email_address"] == "papa@gmail.com"
    assert body["email_address_masked"] == "p***@gmail.com"
    # Not configured yet: no global SMTP sender account has been set up.
    assert body["configured"] is False


@pytest.mark.asyncio
async def test_list_targets_can_filter_by_type(real_api_client: httpx.AsyncClient) -> None:
    await real_api_client.post(
        "/api/v1/notification-targets", json={"type": "ntfy", "name": "A", "topic": "a"}
    )
    await real_api_client.post(
        "/api/v1/notification-targets",
        json={"type": "email", "name": "B", "email_address": "b@x.test"},
    )

    response = await real_api_client.get("/api/v1/notification-targets")
    assert response.status_code == 200
    types = {item["type"] for item in response.json()}
    assert types == {"ntfy", "email"}


@pytest.mark.asyncio
async def test_update_target_can_rename_and_disable_without_touching_secret(
    real_api_client: httpx.AsyncClient,
) -> None:
    created = (
        await real_api_client.post(
            "/api/v1/notification-targets",
            json={"type": "ntfy", "name": "Maxim iPhone", "topic": "kept-topic"},
        )
    ).json()

    response = await real_api_client.patch(
        f"/api/v1/notification-targets/{created['id']}",
        json={"name": "Maxim - neues Handy", "enabled": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Maxim - neues Handy"
    assert body["enabled"] is False
    assert body["ntfy_topic_configured"] is True


@pytest.mark.asyncio
async def test_update_unknown_target_returns_404(real_api_client: httpx.AsyncClient) -> None:
    response = await real_api_client.patch(
        "/api/v1/notification-targets/999999", json={"name": "x"}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_target_reports_how_many_searches_used_it(
    real_api_client: httpx.AsyncClient,
) -> None:
    target = (
        await real_api_client.post(
            "/api/v1/notification-targets",
            json={"type": "ntfy", "name": "Maxim iPhone", "topic": "t"},
        )
    ).json()
    await real_api_client.post(
        "/api/v1/searches",
        json={
            "name": "Search A",
            "category": "marketplace",
            "query": "x",
            "notification_target_ids": [target["id"]],
        },
    )
    await real_api_client.post(
        "/api/v1/searches",
        json={
            "name": "Search B",
            "category": "marketplace",
            "query": "y",
            "notification_target_ids": [target["id"]],
        },
    )

    response = await real_api_client.delete(f"/api/v1/notification-targets/{target['id']}")

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "searches_affected": 2}

    searches = (await real_api_client.get("/api/v1/searches")).json()
    assert len(searches) == 2
    assert all(search["notification_target_ids"] == [] for search in searches)


@pytest.mark.asyncio
async def test_delete_unknown_target_returns_404(real_api_client: httpx.AsyncClient) -> None:
    response = await real_api_client.delete("/api/v1/notification-targets/999999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_test_endpoint_fails_friendly_when_target_not_yet_configured(
    real_api_client: httpx.AsyncClient,
) -> None:
    target = (
        await real_api_client.post(
            "/api/v1/notification-targets", json={"type": "discord", "name": "Not configured"}
        )
    ).json()

    response = await real_api_client.post(f"/api/v1/notification-targets/{target['id']}/test")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_test_endpoint_unknown_target_returns_404(
    real_api_client: httpx.AsyncClient,
) -> None:
    response = await real_api_client.post("/api/v1/notification-targets/999999/test")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_secret_store_file_has_restrictive_permissions(
    real_api_client: httpx.AsyncClient, real_settings: Settings
) -> None:
    await real_api_client.post(
        "/api/v1/notification-targets",
        json={
            "type": "discord",
            "name": "Papa",
            "webhook_url": "https://discord.com/api/webhooks/123456789012345678/aValidToken",
        },
    )
    assert real_settings.secret_store_path is not None
    mode = real_settings.secret_store_path.stat().st_mode & 0o777
    assert mode == 0o600


@pytest.mark.asyncio
async def test_backup_export_excludes_secrets_and_import_links_existing_target(
    real_api_client: httpx.AsyncClient,
) -> None:
    await real_api_client.post(
        "/api/v1/notification-targets",
        json={
            "type": "discord",
            "name": "#willhaben",
            "webhook_url": "https://discord.com/api/webhooks/123456789012345678/aValidToken",
        },
    )
    search = await real_api_client.post(
        "/api/v1/searches",
        json={"name": "Notebook", "category": "marketplace", "query": "ThinkPad"},
    )
    assert search.status_code == 201

    export = await real_api_client.get("/api/v1/backup/export")
    assert export.status_code == 200
    document = export.json()
    assert "aValidToken" not in str(document)
    assert "webhook" not in str(document).lower()
    [target] = document["notification_targets"]
    assert target == {
        "type": "discord",
        "name": "#willhaben",
        "enabled": True,
        "ntfy_base_url": None,
        "email_address": None,
    }

    imported = await real_api_client.post("/api/v1/backup/import", json=document)
    assert imported.status_code == 200
    body = imported.json()
    assert body["notification_targets_skipped"] == 1
    assert body["notification_targets_created"] == 0
    assert body["searches_skipped"] == 1
