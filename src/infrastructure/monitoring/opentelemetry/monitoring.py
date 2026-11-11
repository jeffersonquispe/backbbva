from __future__ import annotations

import json
import time
import uuid
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import metrics, trace
from opentelemetry.trace import (
    NonRecordingSpan,
    Span,
    SpanContext,
    Status,
    StatusCode,
    TraceFlags,
    Tracer,
)

from src.application.ports.monitoring_port import (
    ATTR_OPERATION_TYPE,
    ATTR_RUN_ID,
    ATTR_WORKFLOW_ID,
    RUN_ID_OPERATION_TYPES,
    MonitoringPort,
    OperationalStateSnapshot,
    ResearchCallOutcome,
)
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.opentelemetry.meter import AriaInstruments

# Attributes with an OpenTelemetry GenAI semantic-convention equivalent are
# renamed on write; anything else is kept as a plain attribute.
_GEN_AI_ATTRIBUTE_MAP = {
    "operation_name": "gen_ai.operation.name",
    "provider": "gen_ai.provider.name",
    "model": "gen_ai.request.model",
    "response_model": "gen_ai.response.model",
    "finish_reason": "gen_ai.response.finish_reasons",
    "input_tokens": "gen_ai.usage.input_tokens",
    "output_tokens": "gen_ai.usage.output_tokens",
}

# Span operation types that also feed the gen_ai.client.* metrics.
_GEN_AI_OPERATION_TYPES = frozenset({"llm", "embedding"})
# Only these (low-cardinality) span attributes are copied onto gen_ai.*
# metric points; everything else stays on the span only.
_GEN_AI_METRIC_ATTRIBUTES = (
    "gen_ai.operation.name",
    "gen_ai.provider.name",
    "gen_ai.request.model",
    "gen_ai.response.model",
)


class OpenTelemetrySpan(MonitoringSpan):
    def __init__(
        self,
        span: Span,
        context_token: object,
        operation_type: str = "",
        instruments: AriaInstruments | None = None,
    ) -> None:
        self._span = span
        self._context_token = context_token
        self._operation_type = operation_type
        self._instruments = instruments
        self._started_at = time.perf_counter()
        self._gen_ai_attributes: dict[str, Any] = {}
        self._input_tokens: int | None = None
        self._output_tokens: int | None = None
        self._error_type: str | None = None

    def write_input(self, data: dict[str, Any]) -> None:
        self._write_event("gen_ai.content.prompt", data)

    def write_result(self, data: dict[str, Any]) -> None:
        self._write_event("gen_ai.content.completion", data)

    def write_inner_logs(self, entries: dict[str, Any] | list[dict[str, Any]]) -> None:
        for item in entries if isinstance(entries, list) else [entries]:
            self._write_event("gen_ai.chain_of_thought", item)

    def write_operation_metas(self, metadata: dict[str, Any]) -> None:
        for key, value in metadata.items():
            if value is None:
                continue
            name = _GEN_AI_ATTRIBUTE_MAP.get(key, key)
            self._span.set_attribute(name, value)
            if name in _GEN_AI_METRIC_ATTRIBUTES:
                self._gen_ai_attributes[name] = value
            elif key == "input_tokens":
                self._input_tokens = value
            elif key == "output_tokens":
                self._output_tokens = value

    def record_dependency(
        self,
        name: str,
        kind: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        attributes = {"dependency.name": name, "dependency.kind": kind}
        if metadata:
            attributes.update(_flatten(metadata))
        self._span.add_event("dependency.call", attributes=attributes)

    def finish(self, error: str | None = None) -> None:
        if error is not None:
            self._span.set_status(Status(StatusCode.ERROR, error))
            self._span.record_exception(Exception(error))
        else:
            self._span.set_status(Status(StatusCode.OK))
        self._span.end()
        otel_context.detach(self._context_token)
        self._record_gen_ai_metrics(error)

    def __exit__(self, exc_type, exc, tb) -> None:
        # error.type must be low-cardinality: the exception class, never
        # its message.
        if exc_type is not None:
            self._error_type = exc_type.__name__
        super().__exit__(exc_type, exc, tb)

    def _record_gen_ai_metrics(self, error: str | None) -> None:
        if (
            self._instruments is None
            or self._operation_type not in _GEN_AI_OPERATION_TYPES
        ):
            return
        attributes = dict(self._gen_ai_attributes)
        if error is not None:
            attributes["error.type"] = self._error_type or "_OTHER"
        self._instruments.operation_duration.record(
            time.perf_counter() - self._started_at, attributes=attributes
        )
        for token_type, count in (
            ("input", self._input_tokens),
            ("output", self._output_tokens),
        ):
            if isinstance(count, int):
                self._instruments.token_usage.record(
                    count,
                    attributes={
                        **self._gen_ai_attributes,
                        "gen_ai.token.type": token_type,
                    },
                )

    def _write_event(self, event_name: str, data: dict[str, Any]) -> None:
        # Prompts/completions are opt-in (OTEL_CAPTURE_LLM_CONTENT): by
        # default only record shape/size, never raw content.
        if genai_config.OTEL_CAPTURE_LLM_CONTENT:
            attributes = _flatten(data)
        else:
            attributes = {"content_length": len(json.dumps(data, default=str))}
        self._span.add_event(event_name, attributes=attributes)


class OpenTelemetryMonitoring(MonitoringPort):
    def __init__(self, tracer: Tracer, meter: metrics.Meter | None = None) -> None:
        self._tracer = tracer
        self._instruments = AriaInstruments(
            meter
            if meter is not None
            else metrics.NoOpMeterProvider().get_meter("aria")
        )

    def start(
        self,
        operation_name: str,
        operation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> MonitoringSpan:
        return self._start(operation_name, operation_type, metadata)

    def start_workflow(
        self,
        operation_name: str,
        workflow_execution_id: uuid.UUID,
        operation_type: str = "workflow",
        metadata: dict[str, Any] | None = None,
    ) -> MonitoringSpan:
        # trace_id = the workflow's UUID (128 bits). Derived, not propagated:
        # every attempt/retry/process computes the same id, so no W3C header
        # has to travel in Celery messages. The synthetic remote parent only
        # fixes the trace id; the span itself is the root we export.
        trace_id = workflow_execution_id.int
        if trace_id == 0:
            return self._start(operation_name, operation_type, metadata)
        parent = NonRecordingSpan(
            SpanContext(
                trace_id=trace_id,
                span_id=uuid.uuid4().int & ((1 << 64) - 1) or 1,
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
            )
        )
        return self._start(
            operation_name,
            operation_type,
            {**(metadata or {}), ATTR_WORKFLOW_ID: str(workflow_execution_id)},
            parent_context=trace.set_span_in_context(parent),
        )

    def _start(
        self,
        operation_name: str,
        operation_type: str,
        metadata: dict[str, Any] | None,
        parent_context: otel_context.Context | None = None,
    ) -> MonitoringSpan:
        span = self._tracer.start_span(operation_name, context=parent_context)
        # Activate as the current span so any nested monitoring.start() call
        # (a dependency, a follow-up LLM call, ...) is parented under it and
        # lands in the same trace as the request that triggered it.
        token = otel_context.attach(trace.set_span_in_context(span))
        wrapped = OpenTelemetrySpan(span, token, operation_type, self._instruments)
        wrapped.write_operation_metas(
            {"operation.type": operation_type, ATTR_OPERATION_TYPE: operation_type}
        )
        if operation_type in RUN_ID_OPERATION_TYPES:
            # One id per concrete call; retries of the same logical call
            # inside one span (provider retry loop) share it.
            wrapped.write_operation_metas({ATTR_RUN_ID: str(uuid.uuid4())})
        if metadata:
            wrapped.write_operation_metas(metadata)
        return wrapped

    def record_workflow_duration(
        self, step: str, outcome: str, duration_seconds: float
    ) -> None:
        self._instruments.workflow_duration.record(
            duration_seconds,
            attributes={
                "aria.workflow.step": step,
                "aria.workflow.outcome": str(outcome),
            },
        )

    def record_research_call(self, source: str, outcome: ResearchCallOutcome) -> None:
        self._instruments.research_calls.add(
            1,
            attributes={
                "aria.research.source": source,
                "aria.research.outcome": str(outcome),
            },
        )

    def record_optimizer_iteration(
        self, specialist: str, outcome: str, duration_seconds: float
    ) -> None:
        self._instruments.optimizer_iteration_duration.record(
            duration_seconds,
            attributes={
                "aria.optimizer.specialist": specialist,
                "aria.optimizer.outcome": outcome,
            },
        )

    def record_optimizer_block(self, reason: str) -> None:
        self._instruments.optimizer_blocks.add(
            1, attributes={"aria.optimizer.reason": reason}
        )

    def record_optimizer_recovery(self, reason: str) -> None:
        self._instruments.optimizer_recoveries.add(
            1, attributes={"aria.optimizer.reason": reason}
        )

    def record_rollup_drift(self, data_type: str, level: str, drift: float) -> None:
        self._instruments.rollup_drift.set(
            drift,
            attributes={
                "aria.metrics.data_type": data_type,
                "aria.metrics.level": level,
            },
        )

    def record_operational_state(self, snapshot: OperationalStateSnapshot) -> None:
        i = self._instruments
        i.agent_enabled.set(int(snapshot.agent_enabled))
        i.operating_hours.set(int(snapshot.within_operating_hours))
        i.analyst_queue_depth.set(snapshot.analyst_queue_depth)
        i.analyst_queue_oldest_age.set(snapshot.analyst_queue_oldest_age_seconds)
        i.capacity_available.set(
            snapshot.analysts_available, attributes={"aria.resource": "analyst"}
        )
        i.capacity_available.set(
            snapshot.voicebot_slots_available,
            attributes={"aria.resource": "voicebot"},
        )


def _flatten(data: dict[str, Any]) -> dict[str, Any]:
    """OTEL span attributes must be primitives; JSON-encode nested values."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        flat[key] = (
            value
            if isinstance(value, (str, bool, int, float))
            else json.dumps(value, default=str)
        )
    return flat
