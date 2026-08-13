from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import httpx

from agent.app.core.exceptions import NetworkError, ParseError, RequestTimeoutError


@dataclass(frozen=True, slots=True)
class PublicHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    text: str


class WillhabenHttpClient:
    """Small, bounded HTTP transport for public pages, deliberately without retries."""

    def __init__(
        self,
        *,
        user_agent: str,
        connect_timeout_seconds: float = 10,
        read_timeout_seconds: float = 20,
        max_redirects: int = 3,
        max_response_bytes: int = 5_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self.max_redirects = max_redirects
        self.max_response_bytes = max_response_bytes
        self._client = client

    async def get(self, url: httpx.URL) -> PublicHttpResponse:
        try:
            if self._client is not None:
                return await self._read_response(self._client, url)
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=self.max_redirects,
                timeout=self.timeout,
                headers=self._headers(),
            ) as client:
                return await self._read_response(client, url)
        except httpx.TimeoutException as error:
            raise RequestTimeoutError("Willhaben request timed out") from error
        except httpx.RequestError as error:
            raise NetworkError("Willhaben request failed") from error

    async def _read_response(
        self,
        client: httpx.AsyncClient,
        url: httpx.URL,
    ) -> PublicHttpResponse:
        async with client.stream(
            "GET",
            url,
            headers=self._headers(),
            timeout=self.timeout,
        ) as response:
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > self.max_response_bytes:
                        raise ParseError("Willhaben response exceeds configured size limit")
                except ValueError:
                    pass

            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > self.max_response_bytes:
                    raise ParseError("Willhaben response exceeds configured size limit")
            encoding = response.encoding or "utf-8"
            return PublicHttpResponse(
                status_code=response.status_code,
                headers=dict(response.headers),
                text=content.decode(encoding, errors="replace"),
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": self.user_agent,
        }
