from __future__ import annotations

import socket

from agent.app.core.instance_lock import already_running_message, is_port_available


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def test_is_port_available_true_for_a_free_port() -> None:
    port = _free_port()
    assert is_port_available("127.0.0.1", port) is True


def test_is_port_available_false_while_another_socket_holds_the_port() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        assert is_port_available("127.0.0.1", port) is False
    finally:
        holder.close()


def test_is_port_available_true_again_once_the_holder_releases_it() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    holder.close()

    assert is_port_available("127.0.0.1", port) is True


def test_already_running_message_names_host_and_port_and_is_reassuring() -> None:
    message = already_running_message("127.0.0.1", 8000)
    assert "läuft bereits" in message
    assert "127.0.0.1:8000" in message
    assert "geschlossen werden" in message
