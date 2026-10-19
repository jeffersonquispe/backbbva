from __future__ import annotations

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider

from src.application.ports.monitoring_port import (
    WORKFLOW_TOTAL_STEP,
    MonitoringPort,
    OperationalStateSnapshot,
    ResearchCallOutcome,
)
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.infrastructure.monitoring.opentelemetry.meter import (
    build_meter_provider,
)
from src.infrastructure.monitoring.opentelemetry.monitoring import (
    OpenTelemetryMonitoring,
)

_FORBIDDEN_ATTRIBUTES = {"customer_id", "amount", "aria.amount"}


def _build_monitoring():
    reader = InMemoryMetricReader()
    meter = build_meter_provider([reader]).get_meter("test")
    monitoring = OpenTelemetryMonitoring(TracerProvider().get_tracer("test"), meter)
    return monitoring, reader


def _points(reader: InMemoryMetricReader) -> dict[str, list]:
    data = reader.get_metrics_data()
    points: dict[str, list] = {}
    if data is None:
        return points
    for resource_metrics in data.resource_metrics:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


def _all_attribute_keys(points: dict[str, list]) -> set[str]:
    return {key for pts in points.values() for p in pts for key in p.attributes}


def test_llm_span_records_duration_and_token_usage():
    monitoring, reader = _build_monitoring()

    with monitoring.start(
        "classification_llm_call",
        "llm",
        metadata={
            "operation_name": "classification_llm_call",
            "provider": "azure_openai",
            "model": "gpt-4o",
        },
    ) as span:
        span.write_operation_metas(
            {"input_tokens": 120, "output_tokens": 30, "response_model": "gpt-4o"}
        )

    points = _points(reader)
    (duration,) = points["gen_ai.client.operation.duration"]
    assert duration.count == 1
    assert dict(duration.attributes) == {
        "gen_ai.operation.name": "classification_llm_call",
        "gen_ai.provider.name": "azure_openai",
        "gen_ai.request.model": "gpt-4o",
        "gen_ai.response.model": "gpt-4o",
    }
    tokens = {
        p.attributes["gen_ai.token.type"]: p.sum
        for p in points["gen_ai.client.token.usage"]
    }
    assert tokens == {"input": 120, "output": 30}


def test_failed_llm_span_records_error_type_from_exception_class():
    monitoring, reader = _build_monitoring()

    try:
        with monitoring.start("classification_llm_call", "llm", {"model": "m"}):
            raise TimeoutError("upstream took too long for customer 123")
    except TimeoutError:
        pass

    (duration,) = _points(reader)["gen_ai.client.operation.duration"]
    assert duration.attributes["error.type"] == "TimeoutError"
    assert "gen_ai.client.token.usage" not in _points(reader)


def test_non_llm_span_records_no_gen_ai_metrics():
    monitoring, reader = _build_monitoring()

    with monitoring.start("discard_alert", "use_case"):
        pass

    assert "gen_ai.client.operation.duration" not in _points(reader)


def test_workflow_research_and_drift_instruments():
    monitoring, reader = _build_monitoring()

    monitoring.record_workflow_duration(WORKFLOW_TOTAL_STEP, "CLOSED", 42.0)
    monitoring.record_workflow_duration("classification", "SUCCEEDED", 3.5)
    monitoring.record_research_call("vector_store", ResearchCallOutcome.OK)
    monitoring.record_research_call("vector_store", ResearchCallOutcome.TIMEOUT)
    monitoring.record_research_call("vector_store", ResearchCallOutcome.TIMEOUT)
    monitoring.record_rollup_drift("alert", "day", 3)

    points = _points(reader)
    workflow = {
        p.attributes["aria.workflow.step"]: (
            p.attributes["aria.workflow.outcome"],
            p.sum,
        )
        for p in points["aria.workflow.duration"]
    }
    assert workflow == {
        "workflow": ("CLOSED", 42.0),
        "classification": ("SUCCEEDED", 3.5),
    }
    research = {
        p.attributes["aria.research.outcome"]: p.value
        for p in points["aria.research.calls"]
    }
    assert research == {"ok": 1, "timeout": 2}
    (drift,) = points["aria.metrics.rollup_drift"]
    assert drift.value == 3
    assert dict(drift.attributes) == {
        "aria.metrics.data_type": "alert",
        "aria.metrics.level": "day",
    }


def test_operational_state_gauges():
    monitoring, reader = _build_monitoring()

    monitoring.record_operational_state(
        OperationalStateSnapshot(
            agent_enabled=True,
            within_operating_hours=True,
            analyst_queue_depth=4,
            analyst_queue_oldest_age_seconds=1200.0,
            analysts_available=0,
            voicebot_slots_available=2,
        )
    )

    points = _points(reader)
    assert points["aria.agent.enabled"][0].value == 1
    assert points["aria.operating_hours"][0].value == 1
    assert points["aria.analyst_queue.depth"][0].value == 4
    assert points["aria.analyst_queue.oldest_age"][0].value == 1200.0
    capacity = {
        p.attributes["aria.resource"]: p.value
        for p in points["aria.capacity.available"]
    }
    assert capacity == {"analyst": 0, "voicebot": 2}


def test_metrics_never_carry_customer_or_amount_attributes():
    monitoring, reader = _build_monitoring()

    with monitoring.start(
        "classification_llm_call", "llm", {"model": "m", "customer_id": "C1"}
    ) as span:
        span.write_operation_metas({"amount": 1_500_000, "input_tokens": 1})
    monitoring.record_workflow_duration(WORKFLOW_TOTAL_STEP, "FAILED", 1.0)

    assert not _all_attribute_keys(_points(reader)) & _FORBIDDEN_ATTRIBUTES


def test_port_metric_methods_default_to_no_op_for_existing_fakes():
    class NullSpan(MonitoringSpan):
        def write_input(self, data): ...
        def write_result(self, data): ...
        def write_inner_logs(self, entries): ...
        def write_operation_metas(self, metadata): ...
        def record_dependency(self, name, kind, metadata=None): ...
        def finish(self, error=None): ...

    class NullMonitoring(MonitoringPort):
        def start(self, operation_name, operation_type, metadata=None):
            return NullSpan()

    monitoring = NullMonitoring()
    monitoring.record_workflow_duration("workflow", "CLOSED", 1.0)
    monitoring.record_research_call("vector_store", ResearchCallOutcome.FAILED)
    monitoring.record_rollup_drift("alert", "day", 0)
    monitoring.record_operational_state(
        OperationalStateSnapshot(True, True, 0, 0.0, 1, 1)
    )
