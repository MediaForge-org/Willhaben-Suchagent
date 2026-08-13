from pathlib import Path
from typing import Literal

from pydantic import Field
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
    log_level: str = "INFO"
    marketplace_user_agent: str = (
        "Willhaben-Suchagent/0.2 (public Marketplace search; no authentication)"
    )
    marketplace_connect_timeout_seconds: float = Field(default=10, gt=0)
    marketplace_read_timeout_seconds: float = Field(default=20, gt=0)
    marketplace_max_redirects: int = Field(default=3, ge=0, le=10)
    marketplace_max_response_bytes: int = Field(default=5_000_000, ge=100_000)

    model_config = SettingsConfigDict(
        env_prefix="WILLHABEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
