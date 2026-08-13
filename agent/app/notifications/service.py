from abc import ABC, abstractmethod
from decimal import Decimal
from urllib.parse import quote

import httpx

from agent.app.core.models import Listing


class NotificationDeliveryError(Exception):
    """A configured notification transport could not deliver a message."""


class NotificationDisabledError(Exception):
    """Notification delivery was requested while the transport is disabled."""


class NotificationService(ABC):
    enabled: bool = True
    disabled_reason: str | None = None

    @abstractmethod
    async def notify_new_listing(self, listing: Listing) -> None:
        """Deliver a notification for a globally new listing."""

    async def notify_test(self) -> None:
        """Deliver a user-requested configuration test without creating a listing."""

        raise NotificationDisabledError("Test notifications are not supported")

    async def close(self) -> None:
        """Release transport resources, if any."""

        return None


class FakeNotificationService(NotificationService):
    def __init__(self) -> None:
        self.notifications: list[Listing] = []
        self.test_notification_count = 0

    async def notify_new_listing(self, listing: Listing) -> None:
        self.notifications.append(listing)

    async def notify_test(self) -> None:
        self.test_notification_count += 1


class NtfyNotificationService(NotificationService):
    """Publish listing notifications to one ntfy topic via its HTTP API."""

    LISTING_TITLE = "Neues Willhaben-Inserat"
    TEST_MESSAGE = "Willhaben-Suchagent – Test erfolgreich"

    def __init__(
        self,
        *,
        enabled: bool,
        base_url: str,
        topic: str | None,
        token: str | None = None,
        timeout_seconds: float = 10,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        normalized_topic = topic.strip() if topic else ""
        self.enabled = bool(enabled and base_url.strip() and normalized_topic)
        self.disabled_reason = None
        if not enabled:
            self.disabled_reason = "NTFY_ENABLED is false"
        elif not base_url.strip():
            self.disabled_reason = "NTFY_BASE_URL is empty"
        elif not normalized_topic:
            self.disabled_reason = "NTFY_TOPIC is not configured"

        self._publish_url = f"{base_url.rstrip('/')}/{quote(normalized_topic, safe='')}"
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def notify_new_listing(self, listing: Listing) -> None:
        parts = [listing.title]
        if listing.price is not None:
            parts.append(f"Preis: {self._format_price(listing.price)} €")
        if listing.location:
            parts.append(f"Standort: {listing.location}")
        await self._publish(
            message="\n".join(parts),
            title=self.LISTING_TITLE,
            click=str(listing.url),
        )

    async def notify_test(self) -> None:
        await self._publish(
            message=self.TEST_MESSAGE,
            title="Willhaben-Suchagent",
        )

    async def _publish(self, *, message: str, title: str, click: str | None = None) -> None:
        if not self.enabled:
            raise NotificationDisabledError(self.disabled_reason or "ntfy is disabled")
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": title,
        }
        if click:
            headers["Click"] = click
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            response = await self._client.post(
                self._publish_url,
                content=message.encode("utf-8"),
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise NotificationDeliveryError("ntfy request failed") from error

    @staticmethod
    def _format_price(price: Decimal) -> str:
        formatted = format(price, "f")
        if "." in formatted:
            formatted = formatted.rstrip("0").rstrip(".")
        return formatted

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
