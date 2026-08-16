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
    discord_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("DISCORD_ENABLED", "WILLHABEN_DISCORD_ENABLED"),
    )
    discord_webhook_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DISCORD_WEBHOOK_URL", "WILLHABEN_DISCORD_WEBHOOK_URL"),
    )
    discord_timeout_seconds: float = Field(
        default=10,
        gt=0,
        validation_alias=AliasChoices(
            "DISCORD_TIMEOUT_SECONDS", "WILLHABEN_DISCORD_TIMEOUT_SECONDS"
        ),
    )
    email_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("EMAIL_ENABLED", "WILLHABEN_EMAIL_ENABLED"),
    )
    email_smtp_host: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_SMTP_HOST", "WILLHABEN_EMAIL_SMTP_HOST"),
    )
    email_smtp_port: int = Field(
        default=587,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("EMAIL_SMTP_PORT", "WILLHABEN_EMAIL_SMTP_PORT"),
    )
    email_smtp_username: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_SMTP_USERNAME", "WILLHABEN_EMAIL_SMTP_USERNAME"),
    )
    email_smtp_password: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_SMTP_PASSWORD", "WILLHABEN_EMAIL_SMTP_PASSWORD"),
    )
    email_from_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_FROM_ADDRESS", "WILLHABEN_EMAIL_FROM_ADDRESS"),
    )
    email_to_address: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_TO_ADDRESS", "WILLHABEN_EMAIL_TO_ADDRESS"),
    )
    email_use_tls: bool = Field(
        default=True,
        validation_alias=AliasChoices("EMAIL_USE_TLS", "WILLHABEN_EMAIL_USE_TLS"),
    )
    email_timeout_seconds: float = Field(
        default=10,
        gt=0,
        validation_alias=AliasChoices("EMAIL_TIMEOUT_SECONDS", "WILLHABEN_EMAIL_TIMEOUT_SECONDS"),
    )

    model_config = SettingsConfigDict(
        env_prefix="WILLHABEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
