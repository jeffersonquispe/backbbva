"""RecordAlertMetricsEvent (R4/C4): the ONLY code that writes an alert's
metrics snapshot or the metrics rollups.

Each event: read the alert (and its current snapshot), build the next
snapshot, diff it against the current one (-old +new on every live level)
and hand both to MetricsRollupRepository.apply, which writes them in one
transaction conditioned on snapshot_version. A version conflict (another
event for the same alert won the race) re-reads and retries, up to
MAX_ATTEMPTS. Re-recording an event that changes nothing (e.g. a Celery
retry) is a no-op: no write, no delta - so nothing is ever counted twice."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any
from uuid import UUID

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.alert_schema_port import AlertSchemaRepository
from src.application.ports.clock_port import Clock
from src.application.ports.metrics_rollup_port import (
    AlertSnapshotGuard,
    MetricsRollupRepository,
)
from src.application.ports.monitoring_port import (
    ATTR_ALERT_ID,
    ATTR_RESOLUTION_TIME_SECONDS,
    MonitoringPort,
    span_dimension_attributes,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.metrics.alert_mark_mapping import (
    analyst_resolution,
    voicebot_outcome_mark,
    workflow_resolution,
)
from src.application.use_cases.metrics.alert_rollup_contribution import diff
from src.domain.alerts.amount_tiers import classify_amount
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertRecord,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)
from src.domain.alerts.exceptions import SnapshotVersionConflictError

MAX_ATTEMPTS = 3


def payload_dimensions(
    roles: dict[str, Any],
) -> tuple[str | None, str | None, float | None]:
    """Return dimensions from the canonical role values."""
    channel = roles.get("channel")
    subchannel = roles.get("entrypoint")
    amount = float(roles["amount"]) if roles.get("amount") is not None else None
    return (
        str(channel) if channel is not None else None,
        str(subchannel) if subchannel is not None else None,
        amount,
    )


def canonical_role_values(
    alert: AlertRecord, schemas: AlertSchemaRepository
) -> dict[str, Any]:
    if alert.schema_version is None:
        raise ValueError("Metrics require the alert's processed schema version")
    schema = schemas.get(alert.schema_version)
    if schema is None:
        raise ValueError(f"Schema version {alert.schema_version} not found")
    fields = {field.id: field for field in schema.fields}
    return {
        role: alert.input.get(fields[field_id].field)
        for role, field_id in schema.field_roles.items()
        if field_id in fields
    }


class RecordAlertMetricsEvent:
    def __init__(
        self,
        alert_repository: AlertRepository,
        rollup_repository: MetricsRollupRepository,
        settings_repository: OperationalSettingsRepository,
        timezone_name: str,
        schema_repository: AlertSchemaRepository | None = None,
        clock: Clock | None = None,
        monitoring: MonitoringPort | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._rollups = rollup_repository
        self._settings = settings_repository
        self._schemas = schema_repository
        self._timezone_name = timezone_name
        self._clock = resolve_clock(clock)
        # T2: emits the dedicated "alert.mark_set" span. Optional so the
        # pure-metrics callers/tests can omit it.
        self._monitoring = monitoring

    def execute(
        self, input: RecordAlertMetricsEventInput
    ) -> AlertMetricsSnapshot | None:
        """The stored snapshot after the event, or None if the alert does
        not exist. Raises SnapshotVersionConflictError after MAX_ATTEMPTS
        lost races."""
        occurred_at = input.occurred_at or self._clock.now()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            alert = self._alerts.get(input.alert_id)
            if alert is None:
                return None
            current = alert.metrics
            current_version = current.snapshot_version if current else 0
            proposed = self._next_snapshot(alert, current, input, occurred_at)
            if current is not None and proposed == dataclasses.replace(
                current, snapshot_version=current_version
            ):
                return current
            new = dataclasses.replace(proposed, snapshot_version=current_version + 1)
            deltas = diff(
                current, new, alert.created_at, self._clock.now(), self._timezone_name
            )
            try:
                self._rollups.apply(
                    deltas,
                    AlertSnapshotGuard(
                        alert_id=alert.id,
                        alert_created_at=alert.created_at,
                        expected_version=current_version,
                        snapshot=new,
                    ),
                )
                self._trace_mark_set(alert.id, current, new)
                return new
            except SnapshotVersionConflictError:
                if attempt == MAX_ATTEMPTS:
                    raise
        return None  # unreachable

    def _trace_mark_set(
        self,
        alert_id: UUID,
        current: AlertMetricsSnapshot | None,
        new: AlertMetricsSnapshot,
    ) -> None:
        """One span the moment mark leaves PENDING (it never changes after),
        whoever decided it - ARIA, an analyst or the voicebot."""
        was_pending = current is None or current.mark == Mark.PENDING
        if self._monitoring is None or not was_pending or new.mark == Mark.PENDING:
            return
        metadata: dict[str, Any] = {
            ATTR_ALERT_ID: str(alert_id),
            **span_dimension_attributes(new),
        }
        if new.resolution_time_seconds is not None:
            metadata[ATTR_RESOLUTION_TIME_SECONDS] = new.resolution_time_seconds
        with self._monitoring.start(
            "alert.mark_set", "metrics.mark", metadata=metadata
        ):
            pass

    def execute_backfill(
        self, alert_id: UUID, events: list[RecordAlertMetricsEventInput]
    ) -> tuple[AlertMetricsSnapshot | None, bool]:
        """R6/R7: give an alert that never recorded a metrics event its
        first snapshot, rebuilt from its stored history (`events`, oldest
        first, each with its real occurred_at). All events are folded with
        the same rules as execute() and written as ONE apply at version 1
        (guard: no snapshot stored yet), so a crash mid-way leaves nothing
        half-written.

        An alert that already has a snapshot is left untouched - the live
        events are authoritative - which is what makes a re-run a no-op.
        Returns (stored snapshot or None if the alert doesn't exist,
        whether this call wrote it)."""
        alert = self._alerts.get(alert_id)
        if alert is None:
            return None, False
        if alert.metrics is not None:
            return alert.metrics, False
        snapshot: AlertMetricsSnapshot | None = None
        for event in events:
            snapshot = self._next_snapshot(
                alert, snapshot, event, event.occurred_at or alert.created_at
            )
        if snapshot is None:
            snapshot = self._arrival_snapshot(alert)
        new = dataclasses.replace(snapshot, snapshot_version=1)
        deltas = diff(
            None, new, alert.created_at, self._clock.now(), self._timezone_name
        )
        try:
            self._rollups.apply(
                deltas,
                AlertSnapshotGuard(
                    alert_id=alert.id,
                    alert_created_at=alert.created_at,
                    expected_version=0,
                    snapshot=new,
                ),
            )
        except SnapshotVersionConflictError:
            # A live event wrote the first snapshot meanwhile: it wins.
            current = self._alerts.get(alert_id)
            return (current.metrics if current else None), False
        return new, True

    # --- snapshot construction -------------------------------------------------

    def _next_snapshot(
        self,
        alert: AlertRecord,
        current: AlertMetricsSnapshot | None,
        input: RecordAlertMetricsEventInput,
        occurred_at: datetime,
    ) -> AlertMetricsSnapshot:
        # Version is set by the caller; compare/derive on the current one.
        snapshot = current or self._arrival_snapshot(alert)
        event = input.event_type
        if event == AlertMetricsEventType.CREATED:
            return dataclasses.replace(
                snapshot,
                origin=snapshot.origin or input.origin,
                configuration_id=snapshot.configuration_id or input.configuration_id,
                status=snapshot.status or alert.status,
            )
        if event == AlertMetricsEventType.PRE_PROCESSED:
            # Intake records CREATED before schema preprocessing finishes, so
            # its first snapshot may carry unknown dimensions and no schema
            # version. Once preprocessing updates the canonical alert, rebase
            # the dimensions from that versioned input. The rollup diff moves
            # the count from the provisional bucket to the canonical bucket.
            arrival = (
                self._arrival_snapshot(alert)
                if (
                    snapshot.schema_version is None
                    and self._schemas is not None
                    and alert.schema_version is not None
                )
                else None
            )
            return dataclasses.replace(
                snapshot,
                channel=arrival.channel if arrival is not None else snapshot.channel,
                subchannel=(
                    arrival.subchannel if arrival is not None else snapshot.subchannel
                ),
                amount=arrival.amount if arrival is not None else snapshot.amount,
                amount_tier=(
                    arrival.amount_tier if arrival is not None else snapshot.amount_tier
                ),
                schema_version=(
                    alert.schema_version
                    if alert.schema_version is not None
                    else snapshot.schema_version
                ),
                segment=input.segment
                if input.segment is not None
                else snapshot.segment,
                configuration_id=input.configuration_id or snapshot.configuration_id,
            )
        if event == AlertMetricsEventType.WORKFLOW_FINISHED:
            mark, method = workflow_resolution(input.executed_action)
            snapshot = dataclasses.replace(
                snapshot, status=input.status or alert.status
            )
            return _decide(snapshot, mark, method, occurred_at, alert.created_at)
        if event == AlertMetricsEventType.ANALYST_RESOLVED:
            mark, method = analyst_resolution(input.decision or "")
            snapshot = dataclasses.replace(snapshot, status=AlertStatus.CLOSED)
            return _decide(snapshot, mark, method, occurred_at, alert.created_at)
        if event == AlertMetricsEventType.VOICEBOT_COMPLETED:
            return _decide(
                snapshot,
                voicebot_outcome_mark(input.outcome),
                AlertResolutionMethod.VOICEBOT,
                occurred_at,
                alert.created_at,
            )
        if event == AlertMetricsEventType.FRAUD_REVIEWED:
            if input.fraud_label is None:
                raise ValueError("FRAUD_REVIEWED requires fraud_label")
            return dataclasses.replace(
                snapshot,
                fraud_label=input.fraud_label,
                fraud_reviewed_at=occurred_at,
                fraud_review_count=snapshot.fraud_review_count + 1,
            )
        raise ValueError(f"Unsupported metrics event: {event}")

    def _arrival_snapshot(self, alert: AlertRecord) -> AlertMetricsSnapshot:
        """Build the first snapshot from the alert's canonical input."""
        roles = (
            canonical_role_values(alert, self._schemas)
            if self._schemas is not None and alert.schema_version is not None
            else {
                role: alert.input.get(role)
                for role in ("channel", "entrypoint", "amount")
            }
        )
        dimensions = payload_dimensions(roles)
        channel, subchannel, amount = dimensions
        settings = self._settings.get()
        return AlertMetricsSnapshot(
            channel=channel,
            subchannel=subchannel,
            amount=amount,
            amount_tier=classify_amount(amount, settings.amount_tiers),
            schema_version=alert.schema_version,
            status=alert.status,
        )


def _decide(
    snapshot: AlertMetricsSnapshot,
    mark: Mark,
    method: AlertResolutionMethod | None,
    occurred_at: datetime,
    created_at: datetime,
) -> AlertMetricsSnapshot:
    """Apply a decision. mark is immutable once it left PENDING: later
    decisions only change status (set by the caller). fraud_label is born
    equal to mark, unless the fraud team already reviewed it."""
    if snapshot.mark != Mark.PENDING:
        return snapshot
    snapshot = dataclasses.replace(
        snapshot, resolution_method=method or snapshot.resolution_method
    )
    if mark == Mark.PENDING:
        return snapshot
    return dataclasses.replace(
        snapshot,
        mark=mark,
        marked_at=occurred_at,
        resolution_time_seconds=max((occurred_at - created_at).total_seconds(), 0.0),
        fraud_label=mark
        if snapshot.fraud_reviewed_at is None
        else snapshot.fraud_label,
    )
