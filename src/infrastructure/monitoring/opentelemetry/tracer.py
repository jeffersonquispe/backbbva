from __future__ import annotations

from functools import lru_cache

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.opentelemetry.resource import (
    build_resource,
    otel_export_enabled,
)


@lru_cache(maxsize=1)
def get_tracer() -> trace.Tracer:
    provider = TracerProvider(resource=build_resource())
    if otel_export_enabled():
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=genai_config.OTEL_ENDPOINT)
            )
        )
    trace.set_tracer_provider(provider)
    return trace.get_tracer(genai_config.COMPONENT_NAME)
