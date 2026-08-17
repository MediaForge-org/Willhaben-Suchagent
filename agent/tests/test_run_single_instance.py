from __future__ import annotations

import socket

import pytest

from agent.app import main as main_module


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def test_run_skips_uvicorn_and_prints_friendly_message_when_port_busy(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        monkeypatch.setenv("WILLHABEN_API_HOST", "127.0.0.1")
        monkeypatch.setenv("WILLHABEN_API_PORT", str(port))
        called = False

        def fail_if_called(*args: object, **kwargs: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(main_module.uvicorn, "run", fail_if_called)

        main_module.run()

        assert called is False
        assert "läuft bereits" in capsys.readouterr().out
    finally:
        holder.close()


def test_run_starts_uvicorn_when_port_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _free_port()
    monkeypatch.setenv("WILLHABEN_API_HOST", "127.0.0.1")
    monkeypatch.setenv("WILLHABEN_API_PORT", str(port))
    calls: list[dict[str, object]] = []

    def record(*args: object, **kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(main_module.uvicorn, "run", record)

    main_module.run()

    assert len(calls) == 1
    assert calls[0]["port"] == port
