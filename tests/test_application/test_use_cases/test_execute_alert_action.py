from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.application.dtos.execute_alert_action_dtos import ExecuteAlertActionInput
from src.application.ports.alert_action_port import (
    AlertActionResult,
    AlertChannelActionPort,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.use_cases.alerts.execute_alert_action import (
    ExecuteAlertActionUseCase,
)


class RecordingAlertChannelActionPort(AlertChannelActionPort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, uuid.UUID, str | None]] = []

    def block(self, alert_id, comment=None):
        self.calls.append(("block", alert_id, comment))
        return AlertActionResult(action="block", detail="blocked")

    def route_to_bidi(self, alert_id, comment=None):
        self.calls.append(("bidi", alert_id, comment))
        return AlertActionResult(action="bidi", detail="routed to bidi")

    def route_to_voicebot(self, alert_id, script=None):
        self.calls.append(("voicebot", alert_id, script))
        return AlertActionResult(action="voicebot", detail="routed to voicebot")


class RecordingMonitoringSpan(MonitoringSpan):
    def __init__(self, recorder: list[str]) -> None:
        self._recorder = recorder

    def write_input(self, data: dict[str, Any]) -> None:
        self._recorder.append("write_input")

    def write_result(self, data: dict[str, Any]) -> None:
        self._recorder.append("write_result")

    def write_inner_logs(self, entries) -> None:
        self._recorder.append("write_inner_logs")

    def write_operation_metas(self, metadata: dict[str, Any]) -> None:
        self._recorder.append("write_operation_metas")

    def record_dependency(self, name, kind, metadata=None) -> None:
        self._recorder.append(f"dependency:{name}")

    def finish(self, error: str | None = None) -> None:
        self._recorder.append(f"finish:{error}")


class RecordingMonitoringPort(MonitoringPort):
    def __init__(self) -> None:
        self.events: list[str] = []
        self.started: list[tuple[str, str]] = []

    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        self.started.append((operation_name, operation_type))
        return RecordingMonitoringSpan(self.events)


@pytest.mark.parametrize(
    "action, expected_detail",
    [
        ("block", "blocked"),
        ("bidi", "routed to bidi"),
        ("voicebot", "routed to voicebot"),
    ],
)
def test_execute_alert_action_dispatches_to_matching_port_method(
    action: str, expected_detail: str
) -> None:
    port = RecordingAlertChannelActionPort()
    monitoring = RecordingMonitoringPort()
    use_case = ExecuteAlertActionUseCase(alert_action_port=port, monitoring=monitoring)
    alert_id = uuid.uuid4()

    output = use_case.execute(
        ExecuteAlertActionInput(action=action, alert_id=alert_id)
    )

    assert output.action == action
    assert output.detail == expected_detail
    assert port.calls == [(action, alert_id, None)]
    assert monitoring.started == [("execute_alert_action", "workflow.execution")]
    assert "finish:None" in monitoring.events


def test_execute_alert_action_forwards_generated_content_to_the_port() -> None:
    port = RecordingAlertChannelActionPort()
    use_case = ExecuteAlertActionUseCase(
        alert_action_port=port, monitoring=RecordingMonitoringPort()
    )
    alert_id = uuid.uuid4()

    use_case.execute(
        ExecuteAlertActionInput(action="voicebot", alert_id=alert_id, content="hola")
    )

    assert port.calls == [("voicebot", alert_id, "hola")]


def test_execute_alert_action_rejects_unsupported_action() -> None:
    use_case = ExecuteAlertActionUseCase(
        alert_action_port=RecordingAlertChannelActionPort(),
        monitoring=RecordingMonitoringPort(),
    )

    with pytest.raises(ValueError):
        use_case.execute(
            ExecuteAlertActionInput(action="pass", alert_id=uuid.uuid4())
        )
