"""Platform-appropriate user directories for config, data, and secrets.

These never depend on where the program folder currently lives: the program
folder (venv, source, launcher scripts) may be moved freely, while config and
data stay in the OS-standard per-user locations below. This is what keeps a
relocated install from losing its database, searches, templates, or secrets.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "willhaben-suchagent"


def default_config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME
    return Path.home() / ".config" / APP_DIR_NAME


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def default_database_path() -> Path:
    return default_data_dir() / "willhaben_suchagent.db"


def default_secret_store_path() -> Path:
    return default_data_dir() / "secrets.json"


def default_env_file_path() -> Path:
    return default_config_dir() / "agent.env"
