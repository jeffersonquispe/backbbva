from __future__ import annotations

from src.application.dtos.discard_alert_dtos import (
    DiscardAlertInput,
    DiscardAlertOutput,
)
from src.application.ports.monitoring_port import MonitoringPort


class DiscardAlertUseCase:
    """Terminal step for an alert a DeterministicRule matched against -
    today this only writes a monitoring span recording why the alert was
    discarded before ever reaching profiling/classification/analyst (see
    alert_review_workflow.py's run(), the "deterministic" step). Product
    has a dedicated discard resolution path planned (its own channel
    action, its own AlertStatus, ...) - this use case's call site is
    exactly where that will plug in, so only this class's body should need
    to change then, not the workflow around it. Deliberately shaped like a
    dispatch (alert_id + a reason, called at a pipeline-terminating point)
    even though it doesn't dispatch anywhere yet, since this same
    "terminate the pipeline and just log it for now" pattern is expected
    to recur (e.g. OpsSettings' queue-discard/shortage behaviors)."""

    def __init__(self, monitoring: MonitoringPort) -> None:
        self._monitoring = monitoring

    def execute(self, input: DiscardAlertInput) -> DiscardAlertOutput:
        with self._monitoring.start(
            "discard_alert",
            "workflow.execution",
            metadata={"alert_id": str(input.alert_id)},
        ) as span:
            span.write_input(
                {
                    "rule_id": input.rule_id,
                    "decision": input.decision,
                    "aric_action": input.aric_action,
                }
            )
            span.write_result({"reason": input.reason})
        return DiscardAlertOutput(logged=True)
