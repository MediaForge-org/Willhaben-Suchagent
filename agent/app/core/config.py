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

    model_config = SettingsConfigDict(
        env_prefix="WILLHABEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
