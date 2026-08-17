from __future__ import annotations

import io
import json
import logging
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from agent.app.native_messaging.host import (
    EXTENSION_ID,
    HOST_NAME,
    PROTOCOL_VERSION,
    AgentHttpResponse,
    AgentTransportError,
    LocalAgentClient,
    native_host_manifest,
    read_native_message,
    run_host,
    write_native_message,
)
from agent.app.native_messaging.setup_linux import install, uninstall


def _response(data: object, status: int = 200) -> AgentHttpResponse:
    return AgentHttpResponse(
        status=status,
        body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
    )


def _decode_all(stream: io.BytesIO) -> list[object]:
    stream.seek(0)
    messages: list[object] = []
    while (message := read_native_message(stream)) is not None:
        messages.append(message)
    return messages


def test_native_message_framing_round_trip() -> None:
    stream = io.BytesIO()
    message = {"type": "api.status", "unicode": "Österreich"}

    write_native_message(stream, message)
    stream.seek(0)

    assert read_native_message(stream) == message
    assert read_native_message(stream) is None


@pytest.mark.parametrize(
    ("message", "method", "path", "payload"),
    [
        ({"type": "api.status"}, "GET", "/api/v1/status", None),
        ({"type": "api.settings.get"}, "GET", "/api/v1/settings", None),
        (
            {
                "type": "api.settings.update",
                "payload": {
                    "desktop_sound_enabled": False,
                    "desktop_sound_id": "ping",
                },
            },
            "PATCH",
            "/api/v1/settings",
            {"desktop_sound_enabled": False, "desktop_sound_id": "ping"},
        ),
        ({"type": "api.searches.list"}, "GET", "/api/v1/searches", None),
        (
            {"type": "api.listings.recent", "limit": 17},
            "GET",
            "/api/v1/listings/recent?limit=17",
            None,
        ),
        ({"type": "api.templates.list"}, "GET", "/api/v1/templates", None),
        (
            {"type": "api.marketplace.options"},
            "GET",
            "/api/v1/marketplace/options",
            None,
        ),
        (
            {"type": "api.desktop_sound.test"},
            "POST",
            "/api/v1/desktop-sound/test",
            None,
        ),
        (
            {"type": "api.desktop_sound.test", "soundId": "notify"},
            "POST",
            "/api/v1/desktop-sound/test",
            {"desktop_sound_id": "notify"},
        ),
        (
            {"type": "api.search.create", "payload": {"name": "ThinkPad"}},
            "POST",
            "/api/v1/searches",
            {"name": "ThinkPad"},
        ),
        (
            {"type": "api.search.update", "id": 4, "payload": {"enabled": False}},
            "PATCH",
            "/api/v1/searches/4",
            {"enabled": False},
        ),
        ({"type": "api.search.delete", "id": 4}, "DELETE", "/api/v1/searches/4", None),
        (
            {
                "type": "api.template.create",
                "payload": {"name": "Kauf", "body": "Hallo"},
            },
            "POST",
            "/api/v1/templates",
            {"name": "Kauf", "body": "Hallo"},
        ),
        (
            {"type": "api.template.update", "id": 3, "payload": {"body": "Servus"}},
            "PATCH",
            "/api/v1/templates/3",
            {"body": "Servus"},
        ),
        (
            {"type": "api.template.delete", "id": 3},
            "DELETE",
            "/api/v1/templates/3",
            None,
        ),
        (
            {"type": "api.template.render", "templateId": 3, "listingId": 9},
            "POST",
            "/api/v1/templates/3/render",
            {"listing_id": 9},
        ),
        (
            {
                "type": "api.settings.notifications.update",
                "payload": {"ntfy_timeout_seconds": 15},
            },
            "PATCH",
            "/api/v1/settings/notifications",
            {"ntfy_timeout_seconds": 15},
        ),
        (
            {
                "type": "api.notificationTargets.list",
            },
            "GET",
            "/api/v1/notification-targets",
            None,
        ),
        (
            {
                "type": "api.notificationTargets.create",
                "payload": {"type": "ntfy", "name": "Maxim iPhone", "topic": "x"},
            },
            "POST",
            "/api/v1/notification-targets",
            {"type": "ntfy", "name": "Maxim iPhone", "topic": "x"},
        ),
        (
            {
                "type": "api.notificationTargets.update",
                "id": 4,
                "payload": {"enabled": False},
            },
            "PATCH",
            "/api/v1/notification-targets/4",
            {"enabled": False},
        ),
        (
            {"type": "api.notificationTargets.delete", "id": 4},
            "DELETE",
            "/api/v1/notification-targets/4",
            None,
        ),
        (
            {"type": "api.notificationTargets.test", "id": 4},
            "POST",
            "/api/v1/notification-targets/4/test",
            None,
        ),
        (
            {
                "type": "api.marketplace.import_search_url",
                "url": "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz",
            },
            "POST",
            "/api/v1/marketplace/import-search-url",
            {"url": "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz"},
        ),
        ({"type": "api.backup.export"}, "GET", "/api/v1/backup/export", None),
        (
            {"type": "api.backup.import", "payload": {"format_version": 1, "searches": []}},
            "POST",
            "/api/v1/backup/import",
            {"format_version": 1, "searches": []},
        ),
    ],
)
def test_operations_map_only_to_fixed_agent_endpoints(
    message: dict[str, Any],
    method: str,
    path: str,
    payload: Mapping[str, Any] | None,
) -> None:
    calls: list[tuple[str, str, bytes | None]] = []

    def transport(
        actual_method: str,
        actual_path: str,
        body: bytes | None,
    ) -> AgentHttpResponse:
        calls.append((actual_method, actual_path, body))
        return _response({"accepted": True})

    result = LocalAgentClient(transport).execute(message)

    assert result == {"ok": True, "data": {"accepted": True}}
    assert len(calls) == 1
    actual_method, actual_path, body = calls[0]
    assert (actual_method, actual_path) == (method, path)
    assert (json.loads(body) if body is not None else None) == payload


@pytest.mark.parametrize(
    "message",
    [
        {"type": "api.settings.notifications.update", "payload": {}},
        {"type": "api.settings.notifications.update", "payload": {"unknown_field": "x"}},
        {
            "type": "api.settings.notifications.update",
            "payload": {"email_smtp_port": "587"},
        },
        {
            "type": "api.settings.notifications.update",
            "payload": {"ntfy_timeout_seconds": "fast"},
        },
        {"type": "api.notificationTargets.create", "payload": {}},
        {"type": "api.notificationTargets.create", "payload": {"type": "ntfy"}},
        {
            "type": "api.notificationTargets.create",
            "payload": {"type": "ntfy", "name": "x", "webhook_url": 12345},
        },
        {
            "type": "api.notificationTargets.update",
            "id": 4,
            "payload": {"unknown_field": "x"},
        },
        {"type": "api.notificationTargets.test", "id": 4, "extra": "field"},
        {"type": "api.backup.import"},
        {"type": "api.backup.import", "payload": {}},
        {"type": "api.backup.import", "payload": {"format_version": "1", "searches": []}},
        {"type": "api.backup.import", "payload": {"format_version": 1, "searches": "nope"}},
    ],
)
def test_malformed_notification_settings_payloads_are_rejected_without_request(
    message: dict[str, Any],
) -> None:
    calls: list[tuple[str, str, bytes | None]] = []

    def transport(method: str, path: str, body: bytes | None) -> AgentHttpResponse:
        calls.append((method, path, body))
        return _response({})

    result = LocalAgentClient(transport).execute(message)

    assert result["error"]["kind"] == "broker"
    assert calls == []


@pytest.mark.parametrize(
    "message",
    [
        {"type": "api.marketplace.import_search_url"},
        {"type": "api.marketplace.import_search_url", "url": ""},
        {"type": "api.marketplace.import_search_url", "url": 12345},
        {
            "type": "api.marketplace.import_search_url",
            "url": "https://example.com",
            "extra": "field",
        },
        {"type": "api.marketplace.import_search_url", "url": "x" * 2001},
    ],
)
def test_malformed_import_search_url_payloads_are_rejected_without_request(
    message: dict[str, Any],
) -> None:
    calls: list[tuple[str, str, bytes | None]] = []

    def transport(method: str, path: str, body: bytes | None) -> AgentHttpResponse:
        calls.append((method, path, body))
        return _response({})

    result = LocalAgentClient(transport).execute(message)

    assert result["error"]["kind"] == "broker"
    assert calls == []


def test_unknown_operation_and_arbitrary_url_are_rejected_without_request() -> None:
    calls: list[tuple[str, str, bytes | None]] = []

    def transport(method: str, path: str, body: bytes | None) -> AgentHttpResponse:
        calls.append((method, path, body))
        return _response({})

    client = LocalAgentClient(transport)

    unknown = client.execute({"type": "api.fetch", "url": "https://example.test"})
    injected = client.execute({"type": "api.status", "url": "https://example.test"})
    invalid_sound = client.execute(
        {"type": "api.settings.update", "payload": {"desktop_sound_id": "unknown"}}
    )

    assert unknown["error"]["kind"] == "broker"
    assert injected["error"]["kind"] == "broker"
    assert invalid_sound["error"]["kind"] == "broker"
    assert calls == []


def test_agent_unreachable_is_serialized_as_transport_error() -> None:
    def transport(method: str, path: str, body: bytes | None) -> AgentHttpResponse:
        raise AgentTransportError

    result = LocalAgentClient(transport).execute({"type": "api.status"})

    assert result == {
        "ok": False,
        "error": {
            "kind": "transport",
            "message": "Der Willhaben-Suchagent läuft derzeit nicht.",
        },
    }


def test_agent_http_error_preserves_status_and_safe_detail() -> None:
    client = LocalAgentClient(
        lambda method, path, body: _response({"detail": "Service unavailable"}, 503)
    )

    result = client.execute({"type": "api.status"})

    assert result == {
        "ok": False,
        "error": {"kind": "http", "message": "Service unavailable", "status": 503},
    }


def test_malformed_input_gets_protocol_response_and_host_continues_cleanly() -> None:
    malformed = b"{"
    input_stream = io.BytesIO(struct.pack("<I", len(malformed)) + malformed)
    valid_stream = io.BytesIO()
    write_native_message(
        valid_stream,
        {"requestId": "status-1", "request": {"type": "api.status"}},
    )
    input_stream.seek(0, io.SEEK_END)
    input_stream.write(valid_stream.getvalue())
    input_stream.seek(0)
    output_stream = io.BytesIO()
    log_stream = io.StringIO()
    logger = logging.Logger("native-host-test")
    logger.addHandler(logging.StreamHandler(log_stream))
    client = LocalAgentClient(lambda method, path, body: _response({"ready": True}))

    assert run_host(input_stream, output_stream, client=client, logger=logger) == 0

    assert _decode_all(output_stream) == [
        {
            "requestId": "",
            "protocolVersion": PROTOCOL_VERSION,
            "response": {
                "ok": False,
                "error": {
                    "kind": "data",
                    "message": "Die Native-Host-Anfrage war ungültig.",
                },
            },
        },
        {
            "requestId": "status-1",
            "protocolVersion": PROTOCOL_VERSION,
            "response": {"ok": True, "data": {"ready": True}},
        },
    ]
    assert "native_protocol_error" in log_stream.getvalue()
    assert b"native_protocol_error" not in output_stream.getvalue()
    assert b"native_host_request" not in output_stream.getvalue()


def test_persistent_host_processes_multiple_framed_requests_with_ids() -> None:
    input_stream = io.BytesIO()
    write_native_message(
        input_stream,
        {"requestId": "first", "request": {"type": "api.status"}},
    )
    write_native_message(
        input_stream,
        {
            "requestId": "second",
            "request": {"type": "api.listings.recent", "limit": 1},
        },
    )
    input_stream.seek(0)
    output_stream = io.BytesIO()
    paths: list[str] = []

    def transport(method: str, path: str, body: bytes | None) -> AgentHttpResponse:
        paths.append(path)
        return _response({"path": path})

    assert (
        run_host(
            input_stream,
            output_stream,
            client=LocalAgentClient(transport),
            logger=logging.Logger("persistent-native-host-test"),
        )
        == 0
    )

    assert paths == ["/api/v1/status", "/api/v1/listings/recent?limit=1"]
    assert _decode_all(output_stream) == [
        {
            "requestId": "first",
            "protocolVersion": PROTOCOL_VERSION,
            "response": {"ok": True, "data": {"path": "/api/v1/status"}},
        },
        {
            "requestId": "second",
            "protocolVersion": PROTOCOL_VERSION,
            "response": {
                "ok": True,
                "data": {"path": "/api/v1/listings/recent?limit=1"},
            },
        },
    ]


def test_run_host_stamps_current_protocol_version_on_every_response() -> None:
    input_stream = io.BytesIO()
    write_native_message(
        input_stream,
        {"requestId": "v1", "request": {"type": "api.status"}},
    )
    input_stream.seek(0)
    output_stream = io.BytesIO()
    client = LocalAgentClient(lambda method, path, body: _response({"ok": True}))

    run_host(input_stream, output_stream, client=client, logger=logging.Logger("proto-test"))

    [message] = _decode_all(output_stream)
    assert message["protocolVersion"] == PROTOCOL_VERSION
    assert isinstance(PROTOCOL_VERSION, int)


def test_native_host_manifest_allows_exactly_the_fixed_firefox_extension(tmp_path: Path) -> None:
    executable = tmp_path / HOST_NAME
    executable.touch()

    manifest = native_host_manifest(executable)

    assert manifest == {
        "name": HOST_NAME,
        "description": "Local bridge for the Willhaben-Suchagent Firefox extension",
        "path": str(executable.resolve()),
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],
    }


def test_linux_user_install_uses_absolute_python_without_venv_activation(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    python_executable = tmp_path / "python"
    host_source = project_root / "agent" / "app" / "native_messaging" / "host.py"
    host_source.parent.mkdir(parents=True)
    host_source.write_text("# host\n", encoding="utf-8")
    python_executable.write_text("", encoding="utf-8")

    launcher, manifest_path = install(project_root, python_executable, home)

    installed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert launcher.is_absolute()
    assert launcher.stat().st_mode & 0o777 == 0o700
    assert installed_manifest["path"] == str(launcher)
    assert installed_manifest["allowed_extensions"] == [EXTENSION_ID]
    launcher_text = launcher.read_text(encoding="utf-8")
    assert str(python_executable.resolve()) in launcher_text
    assert "source " not in launcher_text

    removed_launcher, removed_manifest = uninstall(home)
    assert (removed_launcher, removed_manifest) == (launcher, manifest_path)
    assert not launcher.exists()
    assert not manifest_path.exists()


def test_linux_user_install_wraps_bundled_executable_directly_without_python(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    home = tmp_path / "home"
    bundled_host = project_root / "runtime" / "willhaben-suchagent-host"
    bundled_host.parent.mkdir(parents=True)
    bundled_host.write_text("", encoding="utf-8")

    launcher, _manifest_path = install(project_root, None, home, host_executable=bundled_host)

    launcher_text = launcher.read_text(encoding="utf-8")
    assert str(bundled_host.resolve()) in launcher_text
    assert "host.py" not in launcher_text
