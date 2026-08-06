"""
OpenSearch settings for persistence.

Handles creation and instantiation of OpenSearch configuration from environment
or from the application genai config.
"""

from __future__ import annotations

import os
from typing import Optional

from pydantic import BaseModel, Field


class OpenSearchSettings(BaseModel):
    """Settings for OpenSearch connection and chunk index."""

    region: str = Field(default_factory=lambda: os.getenv("OPENSEARCH_REGION", "eu-west-1"))
    index_name: str = Field(
        default_factory=lambda: os.getenv("OPENSEARCH_INDEX", "lupita-vector-index")
    )
    endpoint: str = Field(
        default_factory=lambda: os.getenv("OPENSEARCH_ENDPOINT", "http://localhost:9200")
    )
    timeout: int = Field(default_factory=lambda: int(os.getenv("OPENSEARCH_TIMEOUT", "60")))
    max_retries: int = Field(default_factory=lambda: int(os.getenv("OPENSEARCH_MAX_RETRIES", "3")))
    wait_exponential_jitter: bool = Field(
        default_factory=lambda: os.getenv("OPENSEARCH_WAIT_EXPONENTIAL_JITTER", "true").lower()
        in ("true", "1", "yes")
    )
    user: str = Field(default_factory=lambda: os.getenv("OPENSEARCH_USER", "admin"))
    password: str = Field(default_factory=lambda: os.getenv("OPENSEARCH_PASSWORD", "admin"))
    service: str = Field(default_factory=lambda: os.getenv("OPENSEARCH_SERVICE", "es"))
    environment: str = Field(
        default_factory=lambda: os.getenv("GENAI_ENVIRONMENT", "local")
    )

    @classmethod
    def from_config(cls, config: object) -> OpenSearchSettings:
        """
        Build OpenSearchSettings from an object that has OPENSEARCH_* and GENAI_ENVIRONMENT.
        Pass genai_config (or any config with those attributes) for application-wide settings.
        """

        return cls(
            region=getattr(config, "OPENSEARCH_REGION", "eu-west-1"),
            index_name=getattr(config, "OPENSEARCH_INDEX", "lupita-vector-index"),
            endpoint=getattr(config, "OPENSEARCH_ENDPOINT", "http://localhost:9200"),
            timeout=getattr(config, "OPENSEARCH_TIMEOUT", 60),
            max_retries=getattr(config, "OPENSEARCH_MAX_RETRIES", 3),
            wait_exponential_jitter=getattr(
                config, "OPENSEARCH_WAIT_EXPONENTIAL_JITTER", True
            ),
            user=getattr(config, "OPENSEARCH_USER", "admin"),
            password=getattr(config, "OPENSEARCH_PASSWORD", "admin"),
            service=getattr(config, "OPENSEARCH_SERVICE", "es"),
            environment=getattr(config, "GENAI_ENVIRONMENT", "local"),
        )


def get_opensearch_settings(
    config: Optional[object] = None,
) -> OpenSearchSettings:
    """
    Return OpenSearch settings: from the given config if provided,
    otherwise from environment (singleton-style instance).
    """
    if config is not None:
        return OpenSearchSettings.from_config(config)
    return OpenSearchSettings()


# Default instance from environment (for use when not injecting config)
opensearch_settings = OpenSearchSettings()
