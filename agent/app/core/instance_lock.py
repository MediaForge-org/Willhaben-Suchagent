"""Detect an already-running agent instance before binding the HTTP server.

Uses a plain TCP probe against the configured host/port rather than a pidfile:
it is what actually fails ("address already in use") if a second instance
starts, needs no cleanup on crash, and works identically on Windows and Linux.
"""

from __future__ import annotations

import socket


def is_port_available(host: str, port: int) -> bool:
    """Return True if `host:port` can currently be bound."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError:
        return False
    else:
        return True
    finally:
        probe.close()


ALREADY_RUNNING_MESSAGE = (
    "Willhaben-Suchagent läuft bereits.\n"
    "Es wurde bereits eine laufende Instanz auf {host}:{port} gefunden.\n"
    "Dieses Fenster kann geschlossen werden; die andere Instanz läuft weiter."
)


def already_running_message(host: str, port: int) -> str:
    return ALREADY_RUNNING_MESSAGE.format(host=host, port=port)
