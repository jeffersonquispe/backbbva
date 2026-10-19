from __future__ import annotations

import uuid

from src.application.dtos.discard_alert_dtos import DiscardAlertInput
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.use_cases.alerts.discard_alert import DiscardAlertUseCase


class RecordingMonitoringSpan(MonitoringSpan):
    def __init__(self, recorder: list[str]) -> None:
        self._recorder = recorder
        self.inputs: dict | None = None
        self.results: dict | None = None

    def write_input(self, data) -> None:
        self.inputs = data
        self._recorder.append("write_input")

    def write_result(self, data) -> None:
        self.results = data
        self._recorder.append("write_result")

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata) -> None:
        pass

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error=None) -> None:
        self._recorder.append(f"finish:{error}")


class RecordingMonitoringPort(MonitoringPort):
    def __init__(self) -> None:
        self.events: list[str] = []
        self.started: list[tuple[str, str]] = []
        self.last_span: RecordingMonitoringSpan | None = None

    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        self.started.append((operation_name, operation_type))
        span = RecordingMonitoringSpan(self.events)
        self.last_span = span
        return span


def test_discard_alert_logs_rule_and_reason() -> None:
    monitoring = RecordingMonitoringPort()
    use_case = DiscardAlertUseCase(monitoring=monitoring)
    alert_id = uuid.uuid4()

    output = use_case.execute(
        DiscardAlertInput(
            alert_id=alert_id,
            reason="matched rule r2",
            rule_id="r2",
            decision="risk_suspected",
            aric_action="soft_block",
        )
    )

    assert output.logged is True
    assert monitoring.started == [("discard_alert", "workflow.execution")]
    assert monitoring.last_span.inputs == {
        "rule_id": "r2",
        "decision": "risk_suspected",
        "aric_action": "soft_block",
    }
    assert monitoring.last_span.results == {"reason": "matched rule r2"}
    assert "finish:None" in monitoring.events
