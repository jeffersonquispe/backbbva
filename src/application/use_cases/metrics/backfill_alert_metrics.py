"""BackfillAlertMetrics (R6): give every alert of a date range that never
recorded a metrics event its snapshot and rollup contribution, rebuilt from
what the platform already stored (alert payload/status, workflow execution,
executor step output, analyst/voicebot reservations).

Writes go only through RecordAlertMetricsEvent.execute_backfill (the single
writer of snapshots and rollups): one apply per alert, guarded by "no
snapshot stored yet". Alerts that already have a snapshot are skipped, so
running it again - or concurrently with live traffic - changes nothing:
the numbers after two runs are identical.

Nothing is invented: data that was never persisted (segment; the
configuration resolved at pre_process when the run didn't pin one; origin
of an alert without workflow) stays None -> "unknown" dimension; a decision
that isn't on record stays mark "pending"."""
from __future__ import annotations

from datetime import timedelta

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.metrics_maintenance_dtos import (
    BackfillAlertMetricsInput,
    BackfillAlertMetricsOutput,
)
from src.application.ports.alert_lifecycle_port import (
    AlertLifecycleFacts,
    AlertLifecycleReader,
)
from src.application.ports.alert_port import AlertRecord, AlertRepository, AlertStatus
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)

SCALE_TO_ANALYST = "scale_to_analyst"


def lifecycle_events(
    alert: AlertRecord, facts: AlertLifecycleFacts
) -> list[RecordAlertMetricsEventInput]:
    """The metrics events this alert went through, oldest first, each at
    its stored timestamp - the same events the live hooks would have
    recorded (alert_review_workflow / resolve_escalated_alert /
    complete_voicebot_call)."""
    events = [
        RecordAlertMetricsEventInput(
            alert_id=alert.id,
            event_type=AlertMetricsEventType.CREATED,
            occurred_at=alert.created_at,
            origin=facts.origin,
            configuration_id=facts.configuration_id,
        )
    ]

    def finished(status: AlertStatus, action: str | None = None) -> None:
        events.append(
            RecordAlertMetricsEventInput(
                alert_id=alert.id,
                event_type=AlertMetricsEventType.WORKFLOW_FINISHED,
                occurred_at=workflow.finished_at,
                status=status,
                executed_action=action,
            )
        )

    workflow = facts.workflow
    if workflow is not None:
        if workflow.output_status == "skipped":
            finished(AlertStatus.SKIPPED)
        elif workflow.status == "FAILED":
            finished(AlertStatus.FAILED)
            # A failed review that went to a human (pre_process failure or
            # adversarial loop cap) - see AlertReviewWorkflowRunner.
            if alert.status == AlertStatus.ESCALATED or facts.analyst_resolution:
                finished(AlertStatus.ESCALATED, SCALE_TO_ANALYST)
        else:
            action = (
                "discarded" if workflow.output_status == "discarded"
                else workflow.executed_action
            )
            finished(
                AlertStatus.ESCALATED if action == SCALE_TO_ANALYST else AlertStatus.CLOSED,
                action,
            )

    human: list[RecordAlertMetricsEventInput] = []
    if facts.analyst_resolution is not None:
        human.append(
            RecordAlertMetricsEventInput(
                alert_id=alert.id,
                event_type=AlertMetricsEventType.ANALYST_RESOLVED,
                occurred_at=facts.analyst_resolution.occurred_at,
                decision=facts.analyst_resolution.decision,
            )
        )
    if facts.voicebot_callback is not None:
        human.append(
            RecordAlertMetricsEventInput(
                alert_id=alert.id,
                event_type=AlertMetricsEventType.VOICEBOT_COMPLETED,
                occurred_at=facts.voicebot_callback.occurred_at,
                outcome=facts.voicebot_callback.outcome,
            )
        )
    events.extend(sorted(human, key=lambda event: event.occurred_at))
    return events


class BackfillAlertMetrics:
    def __init__(
        self,
        alert_repository: AlertRepository,
        lifecycle_reader: AlertLifecycleReader,
        recorder: RecordAlertMetricsEvent,
    ) -> None:
        self._alerts = alert_repository
        self._lifecycle = lifecycle_reader
        self._recorder = recorder

    def execute(self, input: BackfillAlertMetricsInput) -> BackfillAlertMetricsOutput:
        if input.to_day < input.from_day:
            raise ValueError("to_day must be >= from_day")
        output = BackfillAlertMetricsOutput()
        day = input.from_day
        while day <= input.to_day:
            output.days += 1
            for alert in self._alerts.list_by_created_day(day):
                output.alerts_seen += 1
                if self.backfill_alert(alert):
                    output.backfilled += 1
                else:
                    output.already_recorded += 1
            day += timedelta(days=1)
        return output

    def backfill_alert(self, alert: AlertRecord) -> bool:
        """True if this call wrote the alert's first snapshot."""
        if alert.metrics is not None:
            return False
        events = lifecycle_events(alert, self._lifecycle.read(alert))
        _, written = self._recorder.execute_backfill(alert.id, events)
        return written
