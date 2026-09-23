from __future__ import annotations

from src.application.dtos.execute_alert_action_dtos import (
    VALID_EXECUTOR_ACTIONS,
    ExecuteAlertActionInput,
    ExecuteAlertActionOutput,
)
from src.application.ports.alert_action_port import AlertChannelActionPort
from src.application.ports.monitoring_port import MonitoringPort


class ExecuteAlertActionUseCase:
    def __init__(
        self,
        alert_action_port: AlertChannelActionPort,
        monitoring: MonitoringPort,
    ) -> None:
        self._alert_action_port = alert_action_port
        self._monitoring = monitoring

    def execute(self, input: ExecuteAlertActionInput) -> ExecuteAlertActionOutput:
        if input.action not in VALID_EXECUTOR_ACTIONS:
            raise ValueError(f"Unsupported alert action: {input.action}")

        with self._monitoring.start(
            "execute_alert_action",
            "workflow.execution",
            metadata={"alert_id": str(input.alert_id), "action": input.action},
        ) as span:
            span.write_input({"action": input.action})
            if input.action == "block":
                result = self._alert_action_port.block(
                    input.alert_id, comment=input.content
                )
            elif input.action == "bidi":
                result = self._alert_action_port.route_to_bidi(
                    input.alert_id, comment=input.content
                )
            else:
                result = self._alert_action_port.route_to_voicebot(
                    input.alert_id, script=input.content
                )
            span.write_result({"action": result.action, "detail": result.detail})
            return ExecuteAlertActionOutput(
                action=result.action, detail=result.detail
            )
