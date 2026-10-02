from __future__ import annotations

import os
import socket
from functools import lru_cache

from opentelemetry.sdk.resources import Resource

from src.infrastructure.core.config import genai_config


def otel_export_enabled() -> bool:
    """Traces, metrics and logs all leave the process only when
    `OTEL_ENDPOINT` is set; an empty value disables every OTLP exporter."""
    return bool(genai_config.OTEL_ENDPOINT.strip())


@lru_cache(maxsize=1)
def build_resource() -> Resource:
    return Resource.create(
        {
            "service.name": genai_config.COMPONENT_NAME,
            "service.version": genai_config.COMPONENT_VERSION,
            "deployment.environment.name": genai_config.GENAI_ENVIRONMENT,
            # One cumulative metric stream per process (gunicorn/celery
            # children export independently; without this they would
            # overwrite each other's series in the Collector).
            "service.instance.id": f"{socket.gethostname()}-{os.getpid()}",
        }
    )
