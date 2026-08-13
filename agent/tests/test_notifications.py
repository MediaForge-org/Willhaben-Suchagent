from collections.abc import Callable

import httpx
import pytest

from agent.app.core.models import Listing
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
            location="Wien",
        )

        await service.notify_new_listing(listing)

    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://ntfy.example.test/private-topic"
    assert request.headers["title"] == "Neues Willhaben-Inserat"
    assert request.headers["click"] == "https://www.willhaben.at/iad/object/123"
    assert request.headers["authorization"] == "Bearer secret-token"
    assert request.content.decode() == ("ThinkPad X1 Carbon\nPreis: 19999.99 €\nStandort: Wien")


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
