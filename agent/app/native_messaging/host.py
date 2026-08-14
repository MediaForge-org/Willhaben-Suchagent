from __future__ import annotations

import argparse
import json
import logging
import struct
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST_NAME = "at.willhaben_suchagent.bridge"
EXTENSION_ID = "willhaben-suchagent@local"
AGENT_BASE_URL = "http://127.0.0.1:8000"
MAX_MESSAGE_BYTES = 1_048_576
REQUEST_TIMEOUT_SECONDS = 10.0

BrokerResponse = dict[str, Any]


class NativeProtocolError(ValueError):
    """One framed native message could not be decoded safely."""


class AgentTransportError(ConnectionError):
    """The native host could not connect to the local Python agent."""


@dataclass(frozen=True, slots=True)
class AgentHttpResponse:
    status: int
    body: bytes


HttpTransport = Callable[[str, str, bytes | None], AgentHttpResponse]


@dataclass(frozen=True, slots=True)
class AgentRequest:
    method: str
    path: str
    payload: Mapping[str, Any] | None = None


class LocalAgentClient:
    """Map a closed set of broker operations to fixed local API requests."""

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._transport = transport or _urllib_transport

    def execute(self, message: object) -> BrokerResponse:
        try:
            request = self._map_request(message)
        except ValueError as error:
            return _error("broker", str(error))

        body = None
        if request.payload is not None:
            body = json.dumps(
                request.payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        try:
            response = self._transport(request.method, request.path, body)
        except AgentTransportError:
            return _error("transport", "Der Willhaben-Suchagent läuft derzeit nicht.")

        if not 200 <= response.status < 300:
            return _error(
                "http",
                _http_error_message(response.body),
                status=response.status,
            )
        if response.status == 204 or not response.body:
            return {"ok": True, "data": None}
        try:
            data = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _error("data", "Die lokale API hat unvollständige Daten geliefert.")
        return {"ok": True, "data": data}

    @staticmethod
    def _map_request(message: object) -> AgentRequest:
        if not isinstance(message, dict):
            raise ValueError("Unbekannte API-Broker-Operation.")
        operation = message.get("type")
        if not isinstance(operation, str):
            raise ValueError("Unbekannte API-Broker-Operation.")

        static_operations = {
            "api.status": AgentRequest("GET", "/api/v1/status"),
            "api.settings.get": AgentRequest("GET", "/api/v1/settings"),
            "api.searches.list": AgentRequest("GET", "/api/v1/searches"),
            "api.templates.list": AgentRequest("GET", "/api/v1/templates"),
            "api.marketplace.options": AgentRequest("GET", "/api/v1/marketplace/options"),
        }
        if operation in static_operations:
            _require_keys(message, {"type"})
            return static_operations[operation]

        if operation == "api.settings.update":
            _require_keys(message, {"type", "payload"})
            return AgentRequest("PATCH", "/api/v1/settings", _settings_payload(message))
        if operation == "api.desktop_sound.test":
            _require_keys(message, {"type", "soundId"}, optional={"soundId"})
            sound_id = message.get("soundId")
            if sound_id is not None and not _is_sound_id(sound_id):
                raise ValueError("Ungültige API-Broker-Anfrage.")
            payload = {"desktop_sound_id": sound_id} if sound_id is not None else None
            return AgentRequest("POST", "/api/v1/desktop-sound/test", payload)

        if operation == "api.listings.recent":
            _require_keys(message, {"type", "limit"}, optional={"limit"})
            limit = message.get("limit", 50)
            if not _is_positive_integer(limit) or limit > 200:
                raise ValueError("Ungültige API-Broker-Anfrage.")
            return AgentRequest("GET", f"/api/v1/listings/recent?limit={limit}")

        if operation == "api.search.create":
            _require_keys(message, {"type", "payload"})
            return AgentRequest("POST", "/api/v1/searches", _payload(message))
        if operation == "api.search.update":
            _require_keys(message, {"type", "id", "payload"})
            identifier = _identifier(message)
            return AgentRequest("PATCH", f"/api/v1/searches/{identifier}", _payload(message))
        if operation == "api.search.delete":
            _require_keys(message, {"type", "id"})
            return AgentRequest("DELETE", f"/api/v1/searches/{_identifier(message)}")

        if operation == "api.template.create":
            _require_keys(message, {"type", "payload"})
            return AgentRequest("POST", "/api/v1/templates", _template_payload(message, False))
        if operation == "api.template.update":
            _require_keys(message, {"type", "id", "payload"})
            identifier = _identifier(message)
            return AgentRequest(
                "PATCH",
                f"/api/v1/templates/{identifier}",
                _template_payload(message, True),
            )
        if operation == "api.template.delete":
            _require_keys(message, {"type", "id"})
            return AgentRequest("DELETE", f"/api/v1/templates/{_identifier(message)}")
        if operation == "api.template.render":
            _require_keys(message, {"type", "templateId", "listingId"})
            template_id = message.get("templateId")
            listing_id = message.get("listingId")
            if not _is_positive_integer(template_id) or not _is_positive_integer(listing_id):
                raise ValueError("Ungültige API-Broker-Anfrage.")
            return AgentRequest(
                "POST",
                f"/api/v1/templates/{template_id}/render",
                {"listing_id": listing_id},
            )
        raise ValueError("Unbekannte API-Broker-Operation.")


def read_native_message(stream: BinaryIO) -> object | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise NativeProtocolError("Truncated native message header")
    (length,) = struct.unpack("<I", header)
    if length == 0 or length > MAX_MESSAGE_BYTES:
        raise NativeProtocolError("Invalid native message length")
    payload = stream.read(length)
    if len(payload) != length:
        raise NativeProtocolError("Truncated native message payload")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise NativeProtocolError("Invalid native message JSON") from error


def write_native_message(stream: BinaryIO, message: Mapping[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise NativeProtocolError("Native response exceeds size limit")
    stream.write(struct.pack("<I", len(payload)))
    stream.write(payload)
    stream.flush()


def run_host(
    input_stream: BinaryIO,
    output_stream: BinaryIO,
    *,
    client: LocalAgentClient | None = None,
    logger: logging.Logger | None = None,
) -> int:
    resolved_client = client or LocalAgentClient()
    resolved_logger = logger or logging.getLogger("willhaben_native_host")
    while True:
        try:
            message = read_native_message(input_stream)
        except NativeProtocolError as error:
            resolved_logger.error("native_protocol_error error=%s", type(error).__name__)
            write_native_message(
                output_stream,
                {
                    "requestId": "",
                    "response": _error(
                        "data",
                        "Die Native-Host-Anfrage war ungültig.",
                    ),
                },
            )
            continue
        if message is None:
            return 0
        request_id, request = _request_envelope(message)
        if request is None:
            resolved_logger.warning("native_host_error operation=unknown kind=broker")
            write_native_message(
                output_stream,
                {
                    "requestId": request_id,
                    "response": _error("broker", "Ungültige Native-Host-Anfrage."),
                },
            )
            continue
        operation = _operation_name(request)
        resolved_logger.info("native_host_request operation=%s", operation)
        response = resolved_client.execute(request)
        error = response.get("error")
        if isinstance(error, dict):
            resolved_logger.warning(
                "native_host_error operation=%s kind=%s",
                operation,
                error.get("kind", "unknown"),
            )
        else:
            resolved_logger.info("native_host_success operation=%s", operation)
        write_native_message(
            output_stream,
            {"requestId": request_id, "response": response},
        )


def native_host_manifest(executable: Path) -> dict[str, Any]:
    absolute = executable.expanduser().resolve()
    if not absolute.is_absolute():
        raise ValueError("Native host executable path must be absolute")
    return {
        "name": HOST_NAME,
        "description": "Local bridge for the Willhaben-Suchagent Firefox extension",
        "path": str(absolute),
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],
    }


def write_host_manifest(destination: Path, executable: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(native_host_manifest(executable), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def _urllib_transport(method: str, path: str, body: bytes | None) -> AgentHttpResponse:
    request = Request(
        f"{AGENT_BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # noqa: S310
            return AgentHttpResponse(status=response.status, body=response.read())
    except HTTPError as error:
        return AgentHttpResponse(status=error.code, body=error.read())
    except (URLError, TimeoutError, OSError) as error:
        raise AgentTransportError from error


def _http_error_message(body: bytes) -> str:
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "Die lokale API-Anfrage ist fehlgeschlagen."
    if isinstance(decoded, dict):
        detail = decoded.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    return "Die lokale API-Anfrage ist fehlgeschlagen."


def _require_keys(
    message: Mapping[str, Any],
    allowed: set[str],
    *,
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    if not set(message) <= allowed or not (allowed - optional) <= set(message):
        raise ValueError("Ungültige API-Broker-Anfrage.")


def _payload(message: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = message.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Ungültige API-Broker-Anfrage.")
    return payload


def _template_payload(message: Mapping[str, Any], allow_partial: bool) -> Mapping[str, Any]:
    payload = _payload(message)
    if not set(payload) <= {"name", "body"}:
        raise ValueError("Ungültige API-Broker-Anfrage.")
    if not allow_partial and set(payload) != {"name", "body"}:
        raise ValueError("Ungültige API-Broker-Anfrage.")
    if allow_partial and not payload:
        raise ValueError("Ungültige API-Broker-Anfrage.")
    if any(not isinstance(value, str) for value in payload.values()):
        raise ValueError("Ungültige API-Broker-Anfrage.")
    return payload


def _settings_payload(message: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = _payload(message)
    if not payload or not set(payload) <= {"desktop_sound_enabled", "desktop_sound_id"}:
        raise ValueError("Ungültige API-Broker-Anfrage.")
    enabled = payload.get("desktop_sound_enabled")
    sound_id = payload.get("desktop_sound_id")
    if enabled is not None and not isinstance(enabled, bool):
        raise ValueError("Ungültige API-Broker-Anfrage.")
    if sound_id is not None and not _is_sound_id(sound_id):
        raise ValueError("Ungültige API-Broker-Anfrage.")
    return payload


def _is_sound_id(value: object) -> bool:
    return isinstance(value, str) and value in {"notify", "ping", "pop"}


def _identifier(message: Mapping[str, Any]) -> int:
    value = message.get("id")
    if not _is_positive_integer(value):
        raise ValueError("Ungültige API-Broker-Anfrage.")
    return value


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _operation_name(message: object) -> str:
    if isinstance(message, dict) and isinstance(message.get("type"), str):
        return message["type"].removeprefix("api.")
    return "unknown"


def _request_envelope(message: object) -> tuple[str, object | None]:
    if not isinstance(message, dict):
        return "", None
    request_id = message.get("requestId")
    request = message.get("request")
    if (
        set(message) != {"requestId", "request"}
        or not isinstance(request_id, str)
        or not request_id
        or len(request_id) > 100
        or not isinstance(request, dict)
    ):
        return request_id if isinstance(request_id, str) else "", None
    return request_id, request


def _error(kind: str, message: str, *, status: int | None = None) -> BrokerResponse:
    error: dict[str, Any] = {"kind": kind, "message": message}
    if status is not None:
        error["status"] = status
    return {"ok": False, "error": error}


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger("willhaben_native_host")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--write-manifest", type=Path)
    parser.add_argument("--executable", type=Path)
    # Firefox may append the calling extension origin/id when it starts a host.
    # These process arguments are metadata only and never influence API routing.
    parser.add_argument("native_metadata", nargs="*")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.write_manifest is not None:
        if args.executable is None:
            raise SystemExit("--executable is required with --write-manifest")
        write_host_manifest(args.write_manifest, args.executable)
        return 0
    _configure_logging()
    return run_host(sys.stdin.buffer, sys.stdout.buffer)


if __name__ == "__main__":
    raise SystemExit(main())
