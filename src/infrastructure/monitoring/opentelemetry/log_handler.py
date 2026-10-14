from __future__ import annotations

import logging
from functools import lru_cache

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry.sdk._logs import (
    LoggerProvider,
    LoggingHandler,
    LogRecordProcessor,
)
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.opentelemetry.resource import (
    build_resource,
    otel_export_enabled,
)


class _DropOwnTelemetryLogs(logging.Filter):
    """The OTLP exporters log their own failures; exporting those through
    the same pipeline would loop forever while the Collector is down."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith("opentelemetry")


class _DropStructuredLogAttributes(logging.Filter):
    """OTLP log attributes must be scalar values or sequences of scalars.

    Celery and other libraries can attach structured payloads as ``data`` on
    log records. The OTEL SDK rejects those dictionaries and emits a warning;
    drop unsupported extras instead of serializing potentially sensitive data.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for name, value in tuple(record.__dict__.items()):
            if name == "data" and isinstance(value, dict):
                del record.__dict__[name]
        return True


def build_logger_provider(processor: LogRecordProcessor) -> LoggerProvider:
    provider = LoggerProvider(resource=build_resource())
    provider.add_log_record_processor(processor)
    return provider


def build_logging_handler(provider: LoggerProvider) -> LoggingHandler:
    """A stdlib handler that ships records over OTLP. The SDK stamps each
    record with the active span's trace_id/span_id, which is what Grafana
    uses to jump between Loki and Tempo."""
    handler = LoggingHandler(level=logging.NOTSET, logger_provider=provider)
    handler.addFilter(_DropOwnTelemetryLogs())
    handler.addFilter(_DropStructuredLogAttributes())
    return handler


@lru_cache(maxsize=1)
def install_otlp_logging() -> LoggingHandler | None:
    """Attach the OTLP handler to the root logger once per process. Gated
    on OTEL_ENDPOINT, like the tracer and the meter."""
    if not otel_export_enabled():
        return None
    provider = build_logger_provider(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=genai_config.OTEL_ENDPOINT))
    )
    set_logger_provider(provider)
    handler = build_logging_handler(provider)
    logging.getLogger().addHandler(handler)
    return handler
