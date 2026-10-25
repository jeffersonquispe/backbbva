from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EventApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EVENT_API_", extra="ignore")

    oidc_issuer: str = ""
    oidc_audience: str = "aria-event-api"
    oidc_jwks_url: str = ""
    oidc_allowed_client_id: str = "frm"
    max_body_bytes: int = Field(default=262144, ge=1)
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/0"
    production_queue: str = "production_events"
    idempotency_ttl_seconds: int = Field(default=2592000, ge=1)


@lru_cache
def event_api_settings() -> EventApiSettings:
    return EventApiSettings()
