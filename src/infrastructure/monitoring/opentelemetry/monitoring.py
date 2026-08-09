from __future__ import annotations

import json
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode, Tracer

from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.infrastructure.core.config import genai_config

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


class OpenTelemetrySpan(MonitoringSpan):
    def __init__(self, span: Span, context_token: object) -> None:
        self._span = span
        self._context_token = context_token

    def write_input(self, data: dict[str, Any]) -> None:
        self._write_event("gen_ai.content.prompt", data)

    def write_result(self, data: dict[str, Any]) -> None:
        self._write_event("gen_ai.content.completion", data)

    def write_inner_logs(
        self, entries: dict[str, Any] | list[dict[str, Any]]
    ) -> None:
        for item in entries if isinstance(entries, list) else [entries]:
            self._write_event("gen_ai.chain_of_thought", item)

    def write_operation_metas(self, metadata: dict[str, Any]) -> None:
        for key, value in metadata.items():
            if value is None:
                continue
            self._span.set_attribute(
                _GEN_AI_ATTRIBUTE_MAP.get(key, key), value
            )

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

    def _write_event(self, event_name: str, data: dict[str, Any]) -> None:
        # Prompts/completions are opt-in (OTEL_CAPTURE_LLM_CONTENT): by
        # default only record shape/size, never raw content.
        if genai_config.OTEL_CAPTURE_LLM_CONTENT:
            attributes = _flatten(data)
        else:
            attributes = {
                "content_length": len(json.dumps(data, default=str))
            }
        self._span.add_event(event_name, attributes=attributes)


class OpenTelemetryMonitoring(MonitoringPort):
    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer

    def start(
        self,
        operation_name: str,
        operation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> MonitoringSpan:
        span = self._tracer.start_span(operation_name)
        # Activate as the current span so any nested monitoring.start() call
        # (a dependency, a follow-up LLM call, ...) is parented under it and
        # lands in the same trace as the request that triggered it.
        token = otel_context.attach(trace.set_span_in_context(span))
        wrapped = OpenTelemetrySpan(span, token)
        wrapped.write_operation_metas({"operation.type": operation_type})
        if metadata:
            wrapped.write_operation_metas(metadata)
        return wrapped


def _flatten(data: dict[str, Any]) -> dict[str, Any]:
    """OTEL span attributes must be primitives; JSON-encode nested values."""
    flat: dict[str, Any] = {}
    for key, value in data.items():
        flat[key] = (
            value if isinstance(value, (str, bool, int, float)) else json.dumps(value, default=str)
        )
    return flat
