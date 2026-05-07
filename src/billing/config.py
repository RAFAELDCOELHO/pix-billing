"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the PIX Billing API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = Field(default="development")
    database_url: str = Field(default="sqlite+aiosqlite:///./pix_billing.db")
    log_level: str = Field(default="INFO")

    pix_merchant_name: str = Field(default="PIX BILLING DEMO")
    pix_merchant_city: str = Field(default="FORTALEZA")
    pix_default_key: str = Field(default="demo@pix-billing.dev")

    charge_default_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    charge_min_cents: int = Field(default=100)
    charge_max_cents: int = Field(default=5_000_000)

    webhook_max_attempts: int = Field(default=3, ge=1, le=10)
    webhook_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    rate_limit_write_per_min: int = Field(default=100)
    rate_limit_read_per_min: int = Field(default=300)

    sentry_dsn: str | None = None
    cloudflare_only: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return process-wide settings singleton."""
    return Settings()
