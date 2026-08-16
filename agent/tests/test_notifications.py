import json
import smtplib
from collections.abc import Callable

import httpx
import pytest

from agent.app.core.models import Listing, SellerType
from agent.app.notifications.service import (
    DiscordNotificationService,
    EmailNotificationService,
    NotificationDeliveryError,
    NotificationDisabledError,
    NtfyNotificationService,
)


@pytest.mark.asyncio
async def test_ntfy_listing_payload_contains_title_message_click_and_token(
    listing_factory: Callable[..., Listing],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NtfyNotificationService(
            enabled=True,
            base_url="https://ntfy.example.test",
            topic="private-topic",
            token="secret-token",
            timeout_seconds=3,
            client=client,
        )
        listing = listing_factory(
            "ntfy-listing",
            title="ThinkPad X1 Carbon",
            url="https://www.willhaben.at/iad/object/123",
            location="Wien, 22. Bezirk",
            seller_name="Beispiel Technik GmbH",
            seller_type=SellerType.COMMERCIAL,
            condition="Sehr gut",
        )

        await service.notify_new_listing(listing)

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://ntfy.example.test/private-topic"
    assert request.headers["title"] == "Neues Willhaben-Inserat"
    assert request.headers["click"] == "https://www.willhaben.at/iad/object/123"
    assert request.headers["authorization"] == "Bearer secret-token"
    assert request.content.decode() == (
        "ThinkPad X1 Carbon\n"
        "19999.99 €\n"
        "Anbieter: Beispiel Technik GmbH\n"
        "Ort: Wien, 22. Bezirk\n"
        "Zustand: Sehr gut"
    )


@pytest.mark.asyncio
async def test_ntfy_omits_all_missing_optional_fields_and_null_representations(
    listing_factory: Callable[..., Listing],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NtfyNotificationService(
            enabled=True,
            base_url="https://ntfy.example.test",
            topic="private-topic",
            client=client,
        )
        listing = listing_factory(
            "minimal",
            title="Nur ein Titel",
            price=None,
            location=None,
            seller_name=None,
            seller_type=None,
            condition=None,
            url="https://www.willhaben.at/iad/object/minimal",
        )

        await service.notify_new_listing(listing)

    message = requests[0].content.decode()
    assert message == "Nur ein Titel"
    assert "none" not in message.casefold()
    assert "null" not in message.casefold()
    assert requests[0].headers["click"] == str(listing.url)
    assert requests[0].headers["priority"] == "high"


@pytest.mark.asyncio
async def test_ntfy_uses_seller_label_for_private_listing(
    listing_factory: Callable[..., Listing],
) -> None:
    requests: list[httpx.Request] = []
    transport = httpx.MockTransport(
        lambda request: requests.append(request) or httpx.Response(200, request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = NtfyNotificationService(
            enabled=True,
            base_url="https://ntfy.example.test",
            topic="private-topic",
            client=client,
        )
        await service.notify_new_listing(
            listing_factory(
                seller_name="Max M.",
                seller_type=SellerType.PRIVATE,
            )
        )

    assert "Verkäufer: Max M." in requests[0].content.decode()


@pytest.mark.asyncio
async def test_ntfy_test_message_uses_no_listing() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NtfyNotificationService(
            enabled=True,
            base_url="https://ntfy.example.test/",
            topic="test-topic",
            client=client,
        )
        await service.notify_test()

    assert requests[0].headers["title"] == "Willhaben-Suchagent"
    assert "click" not in requests[0].headers
    assert "priority" not in requests[0].headers
    assert requests[0].content.decode() == "Willhaben-Suchagent – Test erfolgreich"


@pytest.mark.asyncio
async def test_ntfy_http_failure_is_classified() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        service = NtfyNotificationService(
            enabled=True,
            base_url="https://ntfy.example.test",
            topic="test-topic",
            client=client,
        )
        with pytest.raises(NotificationDeliveryError):
            await service.notify_test()


@pytest.mark.asyncio
async def test_unconfigured_ntfy_is_explicitly_disabled() -> None:
    service = NtfyNotificationService(
        enabled=True,
        base_url="https://ntfy.example.test",
        topic=None,
    )
    try:
        assert service.enabled is False
        assert service.disabled_reason == "NTFY_TOPIC is not configured"
        with pytest.raises(NotificationDisabledError):
            await service.notify_test()
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_discord_listing_payload_posts_webhook_with_title_and_url(
    listing_factory: Callable[..., Listing],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = DiscordNotificationService(
            enabled=True,
            webhook_url="https://discord.example.test/webhook",
            timeout_seconds=3,
            client=client,
        )
        listing = listing_factory(
            "discord-listing",
            title="ThinkPad X1 Carbon",
            url="https://www.willhaben.at/iad/object/456",
        )

        await service.notify_new_listing(listing)

    assert len(requests) == 1
    assert str(requests[0].url) == "https://discord.example.test/webhook"
    payload = json.loads(requests[0].content)
    assert "Neues Willhaben-Inserat" in payload["content"]
    assert "https://www.willhaben.at/iad/object/456" in payload["content"]


@pytest.mark.asyncio
async def test_discord_http_failure_is_classified() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(500, request=request))
    async with httpx.AsyncClient(transport=transport) as client:
        service = DiscordNotificationService(
            enabled=True,
            webhook_url="https://discord.example.test/webhook",
            client=client,
        )
        with pytest.raises(NotificationDeliveryError):
            await service.notify_test()


@pytest.mark.asyncio
async def test_discord_without_webhook_url_is_explicitly_disabled() -> None:
    service = DiscordNotificationService(enabled=True, webhook_url=None)
    try:
        assert service.enabled is False
        assert service.disabled_reason == "DISCORD_WEBHOOK_URL is not configured"
        with pytest.raises(NotificationDisabledError):
            await service.notify_test()
    finally:
        await service.close()


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent_messages: list[object] = []
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = (username, password)

    def send_message(self, message: object) -> None:
        self.sent_messages.append(message)


@pytest.mark.asyncio
async def test_email_listing_notification_sends_via_smtp(
    monkeypatch: pytest.MonkeyPatch,
    listing_factory: Callable[..., Listing],
) -> None:
    _FakeSMTP.instances = []
    monkeypatch.setattr("agent.app.notifications.service.smtplib.SMTP", _FakeSMTP)
    service = EmailNotificationService(
        enabled=True,
        smtp_host="smtp.example.test",
        smtp_port=587,
        username="user",
        password="secret",
        from_address="agent@example.test",
        to_address="me@example.test",
    )
    listing = listing_factory("email-listing", title="ThinkPad X1 Carbon")

    await service.notify_new_listing(listing)

    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.started_tls is True
    assert smtp.logged_in == ("user", "secret")
    assert len(smtp.sent_messages) == 1
    assert smtp.sent_messages[0]["To"] == "me@example.test"


@pytest.mark.asyncio
async def test_email_smtp_failure_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingSMTP(_FakeSMTP):
        def send_message(self, message: object) -> None:
            raise smtplib.SMTPException("simulated smtp failure")

    monkeypatch.setattr("agent.app.notifications.service.smtplib.SMTP", _FailingSMTP)
    service = EmailNotificationService(
        enabled=True,
        smtp_host="smtp.example.test",
        from_address="agent@example.test",
        to_address="me@example.test",
    )

    with pytest.raises(NotificationDeliveryError):
        await service.notify_test()


@pytest.mark.asyncio
async def test_email_without_recipient_is_explicitly_disabled() -> None:
    service = EmailNotificationService(
        enabled=True,
        smtp_host="smtp.example.test",
        from_address="agent@example.test",
        to_address=None,
    )
    assert service.enabled is False
    assert service.disabled_reason == "EMAIL_TO_ADDRESS is not configured"
    with pytest.raises(NotificationDisabledError):
        await service.notify_test()
