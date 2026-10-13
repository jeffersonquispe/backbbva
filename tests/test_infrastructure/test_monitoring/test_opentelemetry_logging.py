from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk._logs.export import (
    InMemoryLogExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace import TracerProvider

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.opentelemetry import log_handler
from src.infrastructure.monitoring.opentelemetry.log_handler import (
    build_logger_provider,
    build_logging_handler,
)
from src.infrastructure.monitoring.opentelemetry.monitoring import (
    OpenTelemetryMonitoring,
)


def _logger_with_handler(name: str):
    exporter = InMemoryLogExporter()
    handler = build_logging_handler(
        build_logger_provider(SimpleLogRecordProcessor(exporter))
    )
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    return logger, handler, exporter


def test_log_record_carries_active_trace_id():
    logger, handler, exporter = _logger_with_handler("aria.test.otlp")
    monitoring = OpenTelemetryMonitoring(TracerProvider().get_tracer("test"))
    try:
        with monitoring.start("post_process", "step"):
            logger.info("step finished")
            expected = trace.get_current_span().get_span_context().trace_id
    finally:
        logger.removeHandler(handler)

    (record,) = exporter.get_finished_logs()
    assert record.log_record.body == "step finished"
    assert record.log_record.trace_id == expected != 0


def test_exporter_own_logs_are_dropped():
    logger, handler, exporter = _logger_with_handler("opentelemetry.exporter.otlp.test")
    try:
        logger.warning("Transient error exporting")
    finally:
        logger.removeHandler(handler)

    assert exporter.get_finished_logs() == ()


def test_install_is_disabled_without_endpoint(monkeypatch):
    monkeypatch.setattr(genai_config, "OTEL_ENDPOINT", "")
    log_handler.install_otlp_logging.cache_clear()
    try:
        assert log_handler.install_otlp_logging() is None
    finally:
        log_handler.install_otlp_logging.cache_clear()
