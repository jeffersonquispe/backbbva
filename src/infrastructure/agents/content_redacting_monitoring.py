from __future__ import annotations

from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan


class _ContentRedactingSpan(MonitoringSpan):
    def __init__(self, span: MonitoringSpan, failure_code: str) -> None:
        self._span = span
        self._failure_code = failure_code

    def write_input(self, data: dict) -> None:
        return None

    def write_result(self, data: dict) -> None:
        return None

    def write_inner_logs(self, entries: dict | list[dict]) -> None:
        return None

    def write_operation_metas(self, metadata: dict) -> None:
        safe = {
            key: value
            for key, value in metadata.items()
            if key in {"model", "provider", "input_tokens", "output_tokens"}
        }
        self._span.write_operation_metas(safe)

    def record_dependency(
        self, name: str, kind: str, metadata: dict | None = None
    ) -> None:
        self._span.record_dependency(name, kind)

    def finish(self, error: str | None = None) -> None:
        self._span.finish(self._failure_code if error else None)


class ContentRedactingMonitoring(MonitoringPort):
    def __init__(
        self, wrapped: MonitoringPort, failure_code: str = "agent_generation_failed"
    ) -> None:
        self._wrapped = wrapped
        self._failure_code = failure_code

    def start(
        self, operation_name: str, operation_type: str, metadata=None
    ) -> MonitoringSpan:
        return _ContentRedactingSpan(
            self._wrapped.start(operation_name, operation_type), self._failure_code
        )
