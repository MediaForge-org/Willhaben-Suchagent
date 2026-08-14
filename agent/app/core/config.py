from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application configuration, overridable through environment variables."""

    cycle_interval_seconds: float = Field(default=60, gt=0)
    max_concurrent_requests: int = Field(default=2, ge=1)
    database_path: Path = Path("data/willhaben_suchagent.db")
    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8000, ge=1, le=65535)
    app_environment: Literal["development", "test", "production"] = "development"
    scheduler_enabled: bool = True
    desktop_sound_enabled: bool = True
    desktop_sound_id: Literal["notify", "ping", "pop"] = "notify"
    log_level: str = "INFO"
    marketplace_user_agent: str = (
        "Willhaben-Suchagent/0.3.1 (public Marketplace pages; no authentication)"
    )
    marketplace_connect_timeout_seconds: float = Field(default=10, gt=0)
    marketplace_read_timeout_seconds: float = Field(default=20, gt=0)
    marketplace_max_redirects: int = Field(default=3, ge=0, le=10)
    marketplace_max_response_bytes: int = Field(default=5_000_000, ge=100_000)
    ntfy_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("NTFY_ENABLED", "WILLHABEN_NTFY_ENABLED"),
    )
    ntfy_base_url: str = Field(
        default="https://ntfy.sh",
        validation_alias=AliasChoices("NTFY_BASE_URL", "WILLHABEN_NTFY_BASE_URL"),
    )
    ntfy_topic: str | None = Field(
        default=None,
        validation_alias=AliasChoices("NTFY_TOPIC", "WILLHABEN_NTFY_TOPIC"),
    )
    ntfy_token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("NTFY_TOKEN", "WILLHABEN_NTFY_TOKEN"),
    )
    ntfy_timeout_seconds: float = Field(
        default=10,
        gt=0,
        validation_alias=AliasChoices(
            "NTFY_TIMEOUT",
            "NTFY_TIMEOUT_SECONDS",
            "WILLHABEN_NTFY_TIMEOUT_SECONDS",
        ),
    )

    model_config = SettingsConfigDict(
        env_prefix="WILLHABEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
