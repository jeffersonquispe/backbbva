from __future__ import annotations

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.opentelemetry.monitoring import (
    OpenTelemetryMonitoring,
)


def _build_monitoring():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(
        resource=Resource.create({"service.name": "test"})
    )
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OpenTelemetryMonitoring(provider.get_tracer("test")), exporter


def test_start_records_operation_metadata_and_succeeds():
    monitoring, exporter = _build_monitoring()

    with monitoring.start(
        "classification_llm_call", "llm", metadata={"model": "gpt-4o"}
    ) as span:
        span.write_operation_metas({"input_tokens": 12})

    (finished,) = exporter.get_finished_spans()
    assert finished.name == "classification_llm_call"
    assert finished.attributes["gen_ai.request.model"] == "gpt-4o"
    assert finished.attributes["gen_ai.usage.input_tokens"] == 12
    assert finished.attributes["operation.type"] == "llm"
    assert finished.status.status_code == StatusCode.OK


def test_finish_records_error_status_on_exception():
    monitoring, exporter = _build_monitoring()

    try:
        with monitoring.start("classification_llm_call", "llm") as span:
            span.write_input({"prompt": "hi"})
            raise ValueError("boom")
    except ValueError:
        pass

    (finished,) = exporter.get_finished_spans()
    assert finished.status.status_code == StatusCode.ERROR
    assert finished.status.description == "boom"


def test_write_input_omits_raw_content_by_default(monkeypatch):
    monkeypatch.setattr(genai_config, "OTEL_CAPTURE_LLM_CONTENT", False)
    monitoring, exporter = _build_monitoring()

    with monitoring.start("classification_llm_call", "llm") as span:
        span.write_input({"prompt": "sensitive data here"})

    (finished,) = exporter.get_finished_spans()
    event = next(
        e for e in finished.events if e.name == "gen_ai.content.prompt"
    )
    assert "prompt" not in event.attributes
    assert "content_length" in event.attributes


def test_write_input_includes_raw_content_when_capture_enabled(monkeypatch):
    monkeypatch.setattr(genai_config, "OTEL_CAPTURE_LLM_CONTENT", True)
    monitoring, exporter = _build_monitoring()

    with monitoring.start("classification_llm_call", "llm") as span:
        span.write_input({"prompt": "sensitive data here"})

    (finished,) = exporter.get_finished_spans()
    event = next(
        e for e in finished.events if e.name == "gen_ai.content.prompt"
    )
    assert event.attributes["prompt"] == "sensitive data here"


def test_record_dependency_adds_event():
    monitoring, exporter = _build_monitoring()

    with monitoring.start("post_process", "step") as span:
        span.record_dependency("workflow_repository", "dynamodb")

    (finished,) = exporter.get_finished_spans()
    event = next(e for e in finished.events if e.name == "dependency.call")
    assert event.attributes["dependency.name"] == "workflow_repository"
    assert event.attributes["dependency.kind"] == "dynamodb"
