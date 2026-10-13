"""R6 backfill + R7 reconciliation (use-case level) with in-memory fakes."""

from __future__ import annotations

import copy
import dataclasses
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.metrics_maintenance_dtos import (
    BackfillAlertMetricsInput,
    ReconcileAlertRollupsInput,
)
from src.application.ports.alert_lifecycle_port import (
    AlertLifecycleFacts,
    AlertLifecycleReader,
    HumanResolutionFacts,
    WorkflowOutcomeFacts,
)
from src.application.ports.alert_port import (
    AlertRecord,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)
from src.application.ports.metrics_rollup_port import (
    RollupKey,
    RollupLevel,
    RollupRow,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.operational_settings_port import OperationalSettings
from src.application.use_cases.metrics.backfill_alert_metrics import (
    BackfillAlertMetrics,
    lifecycle_events,
)
from src.application.use_cases.metrics.reconcile_alert_rollups import (
    ReconcileAlertRollups,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.domain.alerts.exceptions import SnapshotVersionConflictError

TZ = "America/Bogota"
BOG = ZoneInfo(TZ)
NOW = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)  # 02:00 Bogota
DAY = date(2026, 9, 28)
PAYLOAD = {"channel": "WEB", "integrationPoint": "PSE", "amount": {"baseValue": 1500}}


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BOG).astimezone(
        UTC
    )


# --- fakes ------------------------------------------------------------------------


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self.alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    def update(
        self,
        alert_id,
        *,
        status=None,
        async_operation_id=None,
        workflow_execution_id=None,
    ):
        current = self.alerts.get(alert_id)
        if current is None:
            return None
        self.alerts[alert_id] = dataclasses.replace(
            current, status=status or current.status
        )
        return self.alerts[alert_id]

    def list_by_created_day(self, created_day: date) -> list[AlertRecord]:
        return sorted(
            (
                a
                for a in self.alerts.values()
                if a.created_at.astimezone(BOG).date() == created_day
            ),
            key=lambda a: a.created_at,
        )


class InMemoryMetricsRollupRepository:
    """Rows with a revision bumped by every write, like the DynamoDB table:
    apply() is all-or-nothing on the snapshot guard, correct() is
    conditioned on the revision."""

    def __init__(self, alerts: InMemoryAlertRepository) -> None:
        self._alerts = alerts
        self.rows: dict[RollupKey, dict] = {}
        self.corrections: list[RollupKey] = []

    def apply(self, deltas, alert_guard) -> None:
        alert = self._alerts.get(alert_guard.alert_id)
        stored = alert.metrics.snapshot_version if alert and alert.metrics else 0
        if alert is None or stored != alert_guard.expected_version:
            raise SnapshotVersionConflictError(
                str(alert_guard.alert_id), alert_guard.expected_version
            )
        self._alerts.alerts[alert.id] = dataclasses.replace(
            alert, metrics=alert_guard.snapshot
        )
        touched = set()
        for delta in deltas:
            row = self.rows.setdefault(delta.key, {"measures": {}, "rev": 0})
            for measure, value in delta.measures.items():
                row["measures"].setdefault(measure, [0.0] * 24)[delta.hour] += value
            touched.add(delta.key)
        for key in touched:
            self.rows[key]["rev"] += 1

    def query(self, data_type, level, periods, filters=None) -> list[RollupRow]:
        return [
            RollupRow(
                key=key, measures=copy.deepcopy(row["measures"]), revision=row["rev"]
            )
            for key, row in self.rows.items()
            if key.data_type == data_type
            and key.level == level
            and key.period in periods
        ]

    def correct(self, key, measures, expected_revision) -> bool:
        row = self.rows.get(key)
        current = row["rev"] if row is not None else None
        if current != expected_revision:
            return False
        self.rows[key] = {
            "measures": copy.deepcopy(measures),
            "rev": (current or 0) + 1,
        }
        self.corrections.append(key)
        return True

    # helpers
    def find(
        self, level: RollupLevel, period: str, **dims
    ) -> list[tuple[RollupKey, dict]]:
        return [
            (key, row)
            for key, row in self.rows.items()
            if key.level == level
            and key.period == period
            and all(key.dimension(n) == v for n, v in dims.items())
        ]

    def total(
        self, level: RollupLevel, period: str, measure: str = "count", **dims
    ) -> float:
        return sum(
            sum(row["measures"].get(measure, [0.0] * 24))
            for _, row in self.find(level, period, **dims)
        )

    def snapshot_numbers(self) -> dict:
        return {
            key: {m: list(v) for m, v in row["measures"].items()}
            for key, row in self.rows.items()
        }


class StaticSettings:
    def get(self) -> OperationalSettings:
        return OperationalSettings()


class FakeLifecycleReader(AlertLifecycleReader):
    def __init__(self) -> None:
        self.facts: dict[UUID, AlertLifecycleFacts] = {}
        self.reads: list[UUID] = []

    def read(self, alert: AlertRecord) -> AlertLifecycleFacts:
        self.reads.append(alert.id)
        return self.facts.get(alert.id, AlertLifecycleFacts())


class RecordingMonitoring(MonitoringPort):
    def __init__(self) -> None:
        self.drift: list[tuple[str, str, float]] = []

    def start(self, operation_name, operation_type, metadata=None):
        raise NotImplementedError

    def record_rollup_drift(self, data_type: str, level: str, drift: float) -> None:
        self.drift.append((data_type, level, drift))


@pytest.fixture
def env():
    alerts = InMemoryAlertRepository()
    rollups = InMemoryMetricsRollupRepository(alerts)
    reader = FakeLifecycleReader()
    recorder = RecordAlertMetricsEvent(
        alert_repository=alerts,
        rollup_repository=rollups,
        settings_repository=StaticSettings(),
        timezone_name=TZ,
        clock=lambda: NOW,
    )
    backfill = BackfillAlertMetrics(alerts, reader, recorder)
    return alerts, rollups, reader, recorder, backfill


def _alert(
    alerts, created_at: datetime, status=AlertStatus.CLOSED, **kwargs
) -> AlertRecord:
    return alerts.create(
        AlertRecord(
            id=uuid4(),
            event_id=f"evt-{uuid4()}",
            event_type="payment",
            status=status,
            created_at=created_at,
            updated_at=created_at,
            schema_version=1,
            input={"channel": "WEB", "entrypoint": "PSE", "amount": 10},
            workflow_execution_id=uuid4(),
            **kwargs,
        )
    )


def _workflow(
    created_at: datetime,
    action: str | None,
    status="SUCCEEDED",
    output_status="completed",
):
    return WorkflowOutcomeFacts(
        status=status,
        finished_at=created_at + timedelta(minutes=3),
        output_status=output_status,
        executed_action=action,
    )


# --- R6: what a backfilled snapshot says ------------------------------------------


def test_backfill_aria_block_marks_fraud_at_the_workflow_finish(env):
    alerts, _, reader, _, backfill = env
    created = at(DAY, 10)
    alert = _alert(alerts, created)
    reader.facts[alert.id] = AlertLifecycleFacts(
        origin="production",
        configuration_id="cfg-1",
        workflow=_workflow(created, "block"),
    )

    assert backfill.backfill_alert(alert) is True

    snap = alerts.get(alert.id).metrics
    assert (snap.origin, snap.configuration_id, snap.channel, snap.subchannel) == (
        "production",
        "cfg-1",
        "WEB",
        "PSE",
    )
    assert (snap.mark, snap.fraud_label, snap.resolution_method) == (
        Mark.FRAUD,
        Mark.FRAUD,
        AlertResolutionMethod.ARIA,
    )
    assert snap.marked_at == created + timedelta(minutes=3)
    assert snap.resolution_time_seconds == 180
    assert snap.status == AlertStatus.CLOSED and snap.snapshot_version == 1
    # Never persisted -> unknown, not guessed.
    assert snap.segment is None and snap.amount_tier == "unknown"


def test_backfill_escalated_then_analyst_pass(env):
    alerts, _, reader, _, backfill = env
    created = at(DAY, 10)
    alert = _alert(alerts, created)
    resolved_at = created + timedelta(hours=2)
    reader.facts[alert.id] = AlertLifecycleFacts(
        origin="simulator",
        workflow=_workflow(created, "scale_to_analyst"),
        analyst_resolution=HumanResolutionFacts(
            occurred_at=resolved_at, decision="pass"
        ),
    )

    backfill.backfill_alert(alert)

    snap = alerts.get(alert.id).metrics
    assert (snap.mark, snap.resolution_method, snap.status) == (
        Mark.NO_FRAUD,
        AlertResolutionMethod.ANALYST,
        AlertStatus.CLOSED,
    )
    assert snap.marked_at == resolved_at


def test_backfill_voicebot_outcome(env):
    alerts, _, reader, _, backfill = env
    created = at(DAY, 10)
    alert = _alert(alerts, created)
    reader.facts[alert.id] = AlertLifecycleFacts(
        workflow=_workflow(created, "voicebot"),
        voicebot_callback=HumanResolutionFacts(
            occurred_at=created + timedelta(minutes=9), outcome="fraud_confirmed"
        ),
    )

    backfill.backfill_alert(alert)

    snap = alerts.get(alert.id).metrics
    assert (snap.mark, snap.resolution_method) == (
        Mark.FRAUD,
        AlertResolutionMethod.VOICEBOT,
    )
    assert snap.resolution_time_seconds == 9 * 60


def test_backfill_failed_run_escalated_to_a_human_stays_pending(env):
    alerts, _, reader, _, backfill = env
    created = at(DAY, 10)
    alert = _alert(alerts, created, status=AlertStatus.ESCALATED)
    reader.facts[alert.id] = AlertLifecycleFacts(
        workflow=_workflow(created, None, status="FAILED", output_status=None)
    )

    backfill.backfill_alert(alert)

    snap = alerts.get(alert.id).metrics
    assert (snap.mark, snap.resolution_method, snap.status) == (
        Mark.PENDING,
        AlertResolutionMethod.ANALYST,
        AlertStatus.ESCALATED,
    )
    assert snap.marked_at is None


def test_backfill_skipped_and_unknown_history(env):
    alerts, _, reader, _, backfill = env
    skipped = _alert(alerts, at(DAY, 9), status=AlertStatus.SKIPPED)
    reader.facts[skipped.id] = AlertLifecycleFacts(
        origin="production",
        workflow=_workflow(at(DAY, 9), None, output_status="skipped"),
    )
    in_flight = _alert(alerts, at(DAY, 11), status=AlertStatus.PROCESSING)

    backfill.backfill_alert(skipped)
    backfill.backfill_alert(in_flight)

    assert (
        alerts.get(skipped.id).metrics.status,
        alerts.get(skipped.id).metrics.mark,
    ) == (
        AlertStatus.SKIPPED,
        Mark.PENDING,
    )
    snap = alerts.get(in_flight.id).metrics
    assert (snap.origin, snap.status, snap.mark, snap.resolution_method) == (
        None,
        AlertStatus.PROCESSING,
        Mark.PENDING,
        None,
    )


def test_lifecycle_events_are_ordered_and_timestamped():
    created = at(DAY, 10)
    alert = AlertRecord(
        id=uuid4(),
        event_id="e",
        event_type="t",
        input={},
        status=AlertStatus.CLOSED,
        created_at=created,
        updated_at=created,
    )
    facts = AlertLifecycleFacts(
        workflow=_workflow(created, "discarded", output_status="discarded"),
    )

    events = lifecycle_events(alert, facts)

    assert [e.event_type for e in events] == [
        AlertMetricsEventType.CREATED,
        AlertMetricsEventType.WORKFLOW_FINISHED,
    ]
    assert events[0].occurred_at == created
    assert (events[1].executed_action, events[1].status) == (
        "discarded",
        AlertStatus.CLOSED,
    )


# --- R6: idempotency ----------------------------------------------------------------


def test_backfill_twice_gives_identical_numbers_and_skips_recorded_alerts(env):
    alerts, rollups, reader, recorder, backfill = env
    for hour, action in ((8, "block"), (12, "none"), (23, "scale_to_analyst")):
        alert = _alert(alerts, at(DAY, hour))
        reader.facts[alert.id] = AlertLifecycleFacts(
            origin="production", workflow=_workflow(at(DAY, hour), action)
        )
    live = _alert(alerts, at(DAY + timedelta(days=1), 1))
    recorder.execute(
        RecordAlertMetricsEventInput(
            live.id, AlertMetricsEventType.CREATED, origin="manual"
        )
    )
    live_snapshot = alerts.get(live.id).metrics

    first = backfill.execute(BackfillAlertMetricsInput(DAY, DAY + timedelta(days=1)))
    numbers = rollups.snapshot_numbers()
    second = backfill.execute(BackfillAlertMetricsInput(DAY, DAY + timedelta(days=1)))

    assert (
        first.days,
        first.alerts_seen,
        first.backfilled,
        first.already_recorded,
    ) == (2, 4, 3, 1)
    assert (second.backfilled, second.already_recorded) == (0, 4)
    assert rollups.snapshot_numbers() == numbers
    assert alerts.get(live.id).metrics == live_snapshot  # live events win
    assert rollups.total(RollupLevel.DAY, DAY.isoformat(), origin="production") == 3
    assert rollups.total(RollupLevel.DAY, DAY.isoformat(), mark="fraud") == 1
    assert rollups.total(RollupLevel.MONTH, "2026-09", origin="production") == 3


def test_backfill_loses_gracefully_to_a_live_first_event(env):
    alerts, rollups, reader, recorder, _ = env
    alert = _alert(alerts, at(DAY, 10))

    class RacingRecorder(RecordAlertMetricsEvent):
        def execute_backfill(self, alert_id, events):
            recorder.execute(
                RecordAlertMetricsEventInput(
                    alert_id, AlertMetricsEventType.CREATED, origin="live"
                )
            )
            return super().execute_backfill(alert_id, events)

    racing = RacingRecorder(alerts, rollups, StaticSettings(), TZ, clock=lambda: NOW)
    backfill = BackfillAlertMetrics(alerts, reader, racing)
    alerts.alerts[alert.id] = dataclasses.replace(alert, metrics=None)

    assert backfill.backfill_alert(alert) is False
    assert alerts.get(alert.id).metrics.origin == "live"
    assert rollups.total(RollupLevel.DAY, DAY.isoformat()) == 1


def test_backfill_rejects_inverted_range(env):
    *_, backfill = env
    with pytest.raises(ValueError):
        backfill.execute(BackfillAlertMetricsInput(DAY, DAY - timedelta(days=1)))


# --- R7: reconciliation -------------------------------------------------------------


def _reconciler(env, monitoring, sleep=lambda _: None, with_backfill=True):
    alerts, rollups, _, _, backfill = env
    return ReconcileAlertRollups(
        alert_repository=alerts,
        rollup_repository=rollups,
        monitoring=monitoring,
        timezone_name=TZ,
        backfill=backfill if with_backfill else None,
        clock=lambda: NOW,
        settle_seconds=0,
        sleep=sleep,
    )


def _seed(env, n=3, day=DAY):
    alerts, _, _, recorder, _ = env
    ids = []
    for i in range(n):
        alert = _alert(alerts, at(day, 8 + i), status=AlertStatus.PROCESSING)
        recorder.execute(
            RecordAlertMetricsEventInput(
                alert.id, AlertMetricsEventType.CREATED, origin="production"
            )
        )
        recorder.execute(
            RecordAlertMetricsEventInput(
                alert.id,
                AlertMetricsEventType.WORKFLOW_FINISHED,
                occurred_at=at(day, 8 + i, 4),
                status=AlertStatus.CLOSED,
                executed_action="block" if i == 0 else "none",
            )
        )
        ids.append(alert.id)
    return ids


def test_consistent_rollups_report_zero_drift(env):
    _seed(env)
    monitoring = RecordingMonitoring()

    output = _reconciler(env, monitoring).execute(
        ReconcileAlertRollupsInput(day_window=5, month_window=2)
    )

    assert output.drift == 0 and output.corrected == 0
    assert output.days_checked == 5 and output.months_checked == 2
    assert monitoring.drift == [("alert", "day", 0), ("alert", "month", 0)]


def test_a_hand_altered_day_row_is_corrected_and_reported_as_drift_1(env):
    _seed(env)
    _, rollups, *_ = env
    key, row = rollups.find(RollupLevel.DAY, DAY.isoformat(), mark="fraud")[0]
    expected = copy.deepcopy(row["measures"])
    row["measures"]["count"][8] += 5  # hand edit, no revision bump
    monitoring = RecordingMonitoring()

    output = _reconciler(env, monitoring).execute()

    assert output.drift_by_level == {"day": 1, "month": 0}
    assert output.corrected == 1 and output.skipped_concurrent == 0
    assert rollups.rows[key]["measures"]["count"] == expected["count"]
    assert ("alert", "day", 1) in monitoring.drift
    # Idempotent: nothing left to fix.
    assert _reconciler(env, RecordingMonitoring()).execute().drift == 0


def test_a_missing_month_row_is_recreated(env):
    _seed(env)
    _, rollups, *_ = env
    key, row = rollups.find(RollupLevel.MONTH, "2026-09", mark="no_fraud")[0]
    expected = copy.deepcopy(row["measures"])
    del rollups.rows[key]

    output = _reconciler(env, RecordingMonitoring()).execute()

    assert output.drift_by_level == {"day": 0, "month": 1}
    assert rollups.rows[key]["measures"]["count"] == expected["count"]


def test_a_live_write_between_passes_skips_the_correction_without_double_counting(env):
    ids = _seed(env)
    alerts, rollups, _, recorder, _ = env
    key, row = rollups.find(RollupLevel.DAY, DAY.isoformat(), mark="fraud")[0]
    row["measures"]["count"][8] += 5
    fired = []

    def live_event_during_settle(_seconds):
        # A fraud review lands on the drifting row while we wait.
        if not fired:
            fired.append(True)
            recorder.execute(
                RecordAlertMetricsEventInput(
                    ids[0], AlertMetricsEventType.FRAUD_REVIEWED, fraud_label=Mark.FRAUD
                )
            )

    output = _reconciler(
        env, RecordingMonitoring(), sleep=live_event_during_settle
    ).execute()

    assert output.skipped_concurrent >= 1
    assert key not in rollups.corrections
    # The next run (no live traffic) fixes it - and the live delta is kept.
    again = _reconciler(env, RecordingMonitoring()).execute()
    assert again.corrected >= 1
    assert _reconciler(env, RecordingMonitoring()).execute().drift == 0
    assert rollups.total(RollupLevel.DAY, DAY.isoformat()) == 3
    assert (
        rollups.total(RollupLevel.DAY, DAY.isoformat(), measure="reviewed_count") == 1
    )


def test_drift_seen_once_but_gone_on_the_second_read_is_not_corrected(env):
    _seed(env)
    alerts, rollups, *_ = env
    key, row = rollups.find(RollupLevel.DAY, DAY.isoformat(), mark="fraud")[0]
    original = row["measures"]["count"][8]
    row["measures"]["count"][8] += 1

    def heal(_seconds):
        row["measures"]["count"][8] = original  # e.g. a stale read in pass 1

    output = _reconciler(env, RecordingMonitoring(), sleep=heal).execute()

    assert output.drift == 0 and output.corrected == 0


def test_reconciliation_backfills_an_alert_whose_events_were_all_lost(env):
    _seed(env)
    alerts, rollups, reader, _, _ = env
    lost = _alert(alerts, at(DAY, 15))
    reader.facts[lost.id] = AlertLifecycleFacts(
        origin="production", workflow=_workflow(at(DAY, 15), "none")
    )

    output = _reconciler(env, RecordingMonitoring()).execute()

    assert output.snapshots_backfilled == 1 and output.drift == 0
    assert rollups.total(RollupLevel.DAY, DAY.isoformat()) == 4


def test_days_older_than_the_window_are_only_reconciled_through_months(env):
    old_day = date(2026, 8, 3)  # 59 days old, outside a 30-day window
    _seed(env, n=1, day=old_day)
    _, rollups, *_ = env
    key, row = rollups.find(RollupLevel.DAY, old_day.isoformat(), mark="fraud")[0]
    row["measures"]["count"][8] = 99
    month_key, month_row = rollups.find(RollupLevel.MONTH, "2026-08", mark="fraud")[0]
    month_row["measures"]["count"][8] = 99

    output = _reconciler(env, RecordingMonitoring()).execute(
        ReconcileAlertRollupsInput(day_window=30, month_window=6)
    )

    assert output.drift_by_level == {"day": 0, "month": 1}
    assert rollups.rows[key]["measures"]["count"][8] == 99  # outside the day window
    assert rollups.rows[month_key]["measures"]["count"][8] == 1
