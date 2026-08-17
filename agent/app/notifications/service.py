import asyncio
import smtplib
from abc import ABC, abstractmethod
from decimal import Decimal
from email.message import EmailMessage
from typing import Literal
from urllib.parse import quote, urlsplit

import httpx

from agent.app.core.models import Listing, SellerType


class NotificationDeliveryError(Exception):
    """A configured notification transport could not deliver a message."""


class NotificationDisabledError(Exception):
    """Notification delivery was requested while the transport is disabled."""


class InvalidChannelConfigurationError(ValueError):
    """A user-supplied channel configuration failed validation before saving."""


class NotificationService(ABC):
    enabled: bool = True
    disabled_reason: str | None = None
    # Whether the channel has enough non-secret+secret data to ever work, independent
    # of the `enabled` toggle. Drives the extension's "eingerichtet" vs "aktiv" UI.
    configured: bool = False

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
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self.configure(
            enabled=enabled,
            base_url=base_url,
            topic=topic,
            token=token,
            timeout_seconds=timeout_seconds,
        )

    def configure(
        self,
        *,
        enabled: bool,
        base_url: str,
        topic: str | None,
        token: str | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        normalized_topic = topic.strip() if topic else ""
        self.configured = bool(base_url.strip() and normalized_topic)
        self.enabled = bool(enabled and self.configured)
        self.disabled_reason = None
        if not enabled:
            self.disabled_reason = "NTFY_ENABLED is false"
        elif not base_url.strip():
            self.disabled_reason = "NTFY_BASE_URL is empty"
        elif not normalized_topic:
            self.disabled_reason = "NTFY_TOPIC is not configured"

        self.base_url = base_url
        self._publish_url = f"{base_url.rstrip('/')}/{quote(normalized_topic, safe='')}"
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)

    async def notify_new_listing(self, listing: Listing) -> None:
        parts = [listing.article_label]
        if listing.price is not None:
            parts.append(f"{self._format_price(listing.price)} €")
        if listing.seller_name:
            label = "Anbieter" if listing.seller_type is SellerType.COMMERCIAL else "Verkäufer"
            parts.append(f"{label}: {listing.seller_name}")
        if listing.location:
            parts.append(f"Ort: {listing.location}")
        if listing.condition:
            parts.append(f"Zustand: {listing.condition}")
        await self._publish(
            message="\n".join(parts),
            title=self.LISTING_TITLE,
            click=str(listing.url),
            priority="high",
        )

    async def notify_test(self) -> None:
        await self._publish(
            message=self.TEST_MESSAGE,
            title="Willhaben-Suchagent",
        )

    async def _publish(
        self,
        *,
        message: str,
        title: str,
        click: str | None = None,
        priority: str | None = None,
    ) -> None:
        if not self.enabled:
            raise NotificationDisabledError(self.disabled_reason or "ntfy is disabled")
        headers = {
            "Content-Type": "text/plain; charset=utf-8",
            "Title": title,
        }
        if click:
            headers["Click"] = click
        if priority:
            headers["Priority"] = priority
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
        return _format_price(price)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _format_price(price: Decimal) -> str:
    formatted = format(price, "f")
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def _listing_summary_lines(listing: Listing) -> list[str]:
    parts = [listing.article_label]
    if listing.price is not None:
        parts.append(f"{_format_price(listing.price)} €")
    if listing.seller_name:
        label = "Anbieter" if listing.seller_type is SellerType.COMMERCIAL else "Verkäufer"
        parts.append(f"{label}: {listing.seller_name}")
    if listing.location:
        parts.append(f"Ort: {listing.location}")
    if listing.condition:
        parts.append(f"Zustand: {listing.condition}")
    return parts


class DiscordNotificationService(NotificationService):
    """Publish listing notifications to one Discord channel via an incoming webhook."""

    TEST_MESSAGE = "Willhaben-Suchagent – Test erfolgreich"

    _ALLOWED_WEBHOOK_HOSTS = (
        "discord.com",
        "discordapp.com",
        "canary.discord.com",
        "ptb.discord.com",
    )

    def __init__(
        self,
        *,
        enabled: bool,
        webhook_url: str | None,
        timeout_seconds: float = 10,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self.configure(enabled=enabled, webhook_url=webhook_url, timeout_seconds=timeout_seconds)

    def configure(
        self, *, enabled: bool, webhook_url: str | None, timeout_seconds: float = 10
    ) -> None:
        normalized_url = webhook_url.strip() if webhook_url else ""
        self.configured = bool(normalized_url)
        self.enabled = bool(enabled and self.configured)
        self.disabled_reason = None
        if not enabled:
            self.disabled_reason = "DISCORD_ENABLED is false"
        elif not normalized_url:
            self.disabled_reason = "DISCORD_WEBHOOK_URL is not configured"

        self._webhook_url = normalized_url
        self._timeout = httpx.Timeout(timeout_seconds)

    @classmethod
    def _is_well_formed_webhook_url(cls, webhook_url: str) -> bool:
        parts = urlsplit(webhook_url)
        if parts.scheme != "https" or parts.hostname not in cls._ALLOWED_WEBHOOK_HOSTS:
            return False
        segments = [segment for segment in parts.path.split("/") if segment]
        return len(segments) >= 4 and segments[0] == "api" and segments[1] == "webhooks"

    @classmethod
    def validate_webhook_url(cls, webhook_url: str) -> None:
        """Raise before persisting a user-supplied webhook URL that cannot be Discord's."""

        if not cls._is_well_formed_webhook_url(webhook_url):
            raise InvalidChannelConfigurationError(
                "Das sieht nicht nach einer gültigen Discord-Webhook-URL aus."
            )

    async def notify_new_listing(self, listing: Listing) -> None:
        lines = _listing_summary_lines(listing)
        content = "**Neues Willhaben-Inserat**\n" + "\n".join(lines) + f"\n{listing.url}"
        await self._post(content)

    async def notify_test(self) -> None:
        await self._post(self.TEST_MESSAGE)

    async def _post(self, content: str) -> None:
        if not self.enabled:
            raise NotificationDisabledError(self.disabled_reason or "Discord is disabled")
        try:
            response = await self._client.post(
                self._webhook_url,
                json={"content": content},
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise NotificationDeliveryError("Discord webhook request failed") from error

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


EmailEncryption = Literal["starttls", "ssl", "none"]
_EMAIL_ENCRYPTIONS: tuple[EmailEncryption, ...] = ("starttls", "ssl", "none")


class EmailNotificationService(NotificationService):
    """Publish listing notifications as plain-text e-mails via SMTP."""

    TEST_SUBJECT = "Willhaben-Suchagent – Test erfolgreich"

    def __init__(
        self,
        *,
        enabled: bool,
        smtp_host: str | None,
        smtp_port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_address: str | None,
        to_address: str | None,
        use_tls: bool | None = None,
        encryption: EmailEncryption | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.configure(
            enabled=enabled,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            username=username,
            password=password,
            from_address=from_address,
            to_address=to_address,
            use_tls=use_tls,
            encryption=encryption,
            timeout_seconds=timeout_seconds,
        )

    def configure(
        self,
        *,
        enabled: bool,
        smtp_host: str | None,
        smtp_port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_address: str | None,
        to_address: str | None,
        use_tls: bool | None = None,
        encryption: EmailEncryption | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        normalized_host = smtp_host.strip() if smtp_host else ""
        normalized_from = from_address.strip() if from_address else ""
        normalized_to = to_address.strip() if to_address else ""
        self.configured = bool(normalized_host and normalized_from and normalized_to)
        self.enabled = bool(enabled and self.configured)
        self.disabled_reason = None
        if not enabled:
            self.disabled_reason = "EMAIL_ENABLED is false"
        elif not normalized_host:
            self.disabled_reason = "EMAIL_SMTP_HOST is not configured"
        elif not normalized_from:
            self.disabled_reason = "EMAIL_FROM_ADDRESS is not configured"
        elif not normalized_to:
            self.disabled_reason = "EMAIL_TO_ADDRESS is not configured"

        if encryption is not None:
            resolved_encryption: EmailEncryption = encryption
        else:
            resolved_encryption = "starttls" if (use_tls is None or use_tls) else "none"

        self._smtp_host = normalized_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_address = normalized_from
        self._to_address = normalized_to
        self._encryption: EmailEncryption = resolved_encryption
        self._timeout_seconds = timeout_seconds

    @property
    def use_tls(self) -> bool:
        return self._encryption == "starttls"

    @property
    def encryption(self) -> EmailEncryption:
        return self._encryption

    async def notify_new_listing(self, listing: Listing) -> None:
        lines = _listing_summary_lines(listing)
        body = "\n".join([*lines, "", str(listing.url)])
        await self._send(subject=f"Neues Willhaben-Inserat: {listing.article_label}", body=body)

    async def notify_test(self) -> None:
        await self._send(subject=self.TEST_SUBJECT, body=self.TEST_SUBJECT)

    async def _send(self, *, subject: str, body: str) -> None:
        if not self.enabled:
            raise NotificationDisabledError(self.disabled_reason or "E-Mail is disabled")
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._from_address
        message["To"] = self._to_address
        message.set_content(body)
        try:
            await asyncio.to_thread(self._send_sync, message)
        except (OSError, smtplib.SMTPException) as error:
            raise NotificationDeliveryError("SMTP-Anmeldung fehlgeschlagen.") from error

    def _send_sync(self, message: EmailMessage) -> None:
        smtp_class = smtplib.SMTP_SSL if self._encryption == "ssl" else smtplib.SMTP
        with smtp_class(self._smtp_host, self._smtp_port, timeout=self._timeout_seconds) as smtp:
            if self._encryption == "starttls":
                smtp.starttls()
            if self._username and self._password:
                smtp.login(self._username, self._password)
            smtp.send_message(message)
