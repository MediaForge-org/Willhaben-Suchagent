"""Backup file shape.

Deliberately permissive (``extra="ignore"``) unlike the API-facing schemas in
``agent.app.api.schemas``: a backup file is a document meant to keep working
across app versions, not a single request whose exact shape should be
enforced strictly. Unknown fields (e.g. written by a future app version) are
ignored rather than rejected, so importing a newer backup into an older
release degrades gracefully instead of failing outright.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BACKUP_FORMAT_VERSION = 1

NotificationTargetType = Literal["ntfy", "discord", "email"]


class BackupTemplate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)


class BackupNotificationTarget(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: NotificationTargetType
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    ntfy_base_url: str | None = None
    email_address: str | None = None


class BackupSearchTargetRef(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: NotificationTargetType
    name: str = Field(min_length=1, max_length=200)


class BackupSearch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=200)
    category: Literal["marketplace"] = "marketplace"
    enabled: bool = True
    query: str = Field(default="", max_length=500)
    location: str | None = Field(default=None, max_length=300)
    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)
    category_filters: dict[str, object] = Field(default_factory=dict)
    notify_desktop_sound: bool = True
    notification_targets: list[BackupSearchTargetRef] = Field(default_factory=list)
    default_template_name: str | None = None


class BackupFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format_version: int
    app_version: str = ""
    exported_at: str = ""
    templates: list[BackupTemplate] = Field(default_factory=list)
    notification_targets: list[BackupNotificationTarget] = Field(default_factory=list)
    searches: list[BackupSearch] = Field(default_factory=list)
