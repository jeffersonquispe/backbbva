from __future__ import annotations

from functools import lru_cache

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from src.infrastructure.core.config import genai_config


@lru_cache(maxsize=1)
def get_tracer() -> trace.Tracer:
    resource = Resource.create(
        {
            "service.name": genai_config.COMPONENT_NAME,
            "service.version": genai_config.COMPONENT_VERSION,
            "deployment.environment.name": genai_config.GENAI_ENVIRONMENT,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=genai_config.OTEL_ENDPOINT)
        )
    )
    trace.set_tracer_provider(provider)
    return trace.get_tracer(genai_config.COMPONENT_NAME)
