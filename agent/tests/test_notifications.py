from collections.abc import Callable

import httpx
import pytest

from agent.app.core.models import Listing, SellerType
from agent.app.notifications.service import (
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
