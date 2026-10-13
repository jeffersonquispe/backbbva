"""R4 writer + C4 hook points (use-case level) with in-memory fakes."""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from src.application.dtos.alert_dtos import StartAlertWorkflowInput
from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.analyst_queue_dtos import ResolveEscalatedAlertInput
from src.application.ports.alert_action_dispatcher_port import AlertActionDispatchRef
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaVersion,
)
from src.application.ports.metrics_rollup_port import (
    AlertSnapshotGuard,
    RollupDelta,
    RollupLevel,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.ports.operational_settings_port import (
    AmountTier,
    OperationalSettings,
)
from src.application.ports.resource_reservation_port import (
    ReservationStatus,
    ReservedResource,
    ResourceReservation,
)
from src.application.ports.workflow_executor_port import WorkflowExecutionRef
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.application.use_cases.analyst_queue.resolve_escalated_alert import (
    ResolveEscalatedAlertUseCase,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    MAX_ATTEMPTS,
    RecordAlertMetricsEvent,
)
from src.application.use_cases.operations.complete_voicebot_call import (
    CompleteVoicebotCallUseCase,
)
from src.domain.alerts.entities import (
    AlertMetricsSnapshot,
    AlertOrigin,
    AlertRecord,
    AlertResolutionMethod,
    AlertStatus,
    Mark,
)
from src.domain.alerts.exceptions import SnapshotVersionConflictError
from src.domain.configurations.entities import (
    ConfigurationRef,
)

TZ = "America/Bogota"
CREATED_AT = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)  # 09:00 Bogota
NOW = CREATED_AT + timedelta(minutes=4)

PAYLOAD = {
    "eventId": "evt-1",
    "channel": "WEB",
    "integrationPoint": "PSE",
    "amount": {"baseValue": 2_500_000},
}
TIERS = [
    AmountTier("low", "< 1M", 0, 1_000_000),
    AmountTier("mid", "1M-3M", 1_000_000, 3_000_000),
    AmountTier("high", "> 3M", 3_000_000, None),
]


# --- fakes ------------------------------------------------------------------------


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(
        self, alert: AlertRecord, *, raw_payload: dict[str, Any] | None = None
    ) -> AlertRecord:
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
        updated = dataclasses.replace(
            current,
            status=status or current.status,
            async_operation_id=async_operation_id or current.async_operation_id,
            workflow_execution_id=workflow_execution_id
            or current.workflow_execution_id,
        )
        self.alerts[alert_id] = updated
        return updated


class InMemoryMetricsRollupRepository:
    """Applies the guard like the DynamoDB transaction: all-or-nothing,
    conditioned on the stored snapshot_version."""

    def __init__(self, alerts: InMemoryAlertRepository) -> None:
        self._alerts = alerts
        self.rows: dict = defaultdict(lambda: defaultdict(float))
        self.applies: list[tuple[list[RollupDelta], AlertSnapshotGuard]] = []
        self.conflicts = 0
        # Callables run right before the next apply (simulate a racing writer).
        self.before_apply: list = []

    def apply(self, deltas, alert_guard) -> None:
        if self.before_apply:
            self.before_apply.pop(0)()
        alert = self._alerts.get(alert_guard.alert_id)
        stored = alert.metrics.snapshot_version if alert and alert.metrics else 0
        if alert is None or stored != alert_guard.expected_version:
            self.conflicts += 1
            raise SnapshotVersionConflictError(
                str(alert_guard.alert_id), alert_guard.expected_version
            )
        self.applies.append((deltas, alert_guard))
        self._alerts.alerts[alert.id] = dataclasses.replace(
            alert, metrics=alert_guard.snapshot
        )
        for delta in deltas:
            for measure, value in delta.measures.items():
                self.rows[(delta.key, delta.hour)][measure] += value

    def query(self, data_type, level, periods, filters=None):
        raise NotImplementedError

    def total(
        self, measure: str, level: RollupLevel = RollupLevel.DAY, **dims
    ) -> float:
        return sum(
            measures.get(measure, 0)
            for (key, _hour), measures in self.rows.items()
            if key.level == level
            and all(key.dimension(name) == value for name, value in dims.items())
        )


class InMemoryOperationalSettingsRepository:
    def __init__(self, settings: OperationalSettings) -> None:
        self.settings = settings

    def get(self) -> OperationalSettings:
        return self.settings


class InMemoryAlertSchemaRepository:
    def get(self, version: int):
        fields = [
            AlertSchemaField(
                "channel",
                AlertSchemaDataSource.ARIC,
                "channel",
                type=AlertSchemaFieldType.STRING,
            ),
            AlertSchemaField(
                "entrypoint",
                AlertSchemaDataSource.ARIC,
                "entrypoint",
                type=AlertSchemaFieldType.STRING,
            ),
            AlertSchemaField(
                "amount",
                AlertSchemaDataSource.ARIC,
                "amount",
                type=AlertSchemaFieldType.NUMBER,
            ),
        ]
        return AlertSchemaVersion(
            version=version,
            fields=fields,
            field_roles={
                "channel": "channel",
                "entrypoint": "entrypoint",
                "amount": "amount",
            },
        )


def _alert(alerts: InMemoryAlertRepository, payload=PAYLOAD) -> AlertRecord:
    channel = payload.get("channel")
    entrypoint = (
        payload.get("entrypoint")
        or payload.get("integrationpoint")
        or payload.get("integrationPoint")
    )
    amount = payload.get("amount")
    if isinstance(amount, dict):
        amount = amount.get("baseValue")
    amount = payload.get("amount_value", amount)
    return alerts.create(
        AlertRecord(
            id=uuid4(),
            event_id="evt-1",
            event_type="payment",
            status=AlertStatus.PROCESSING,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
            schema_version=1,
            input={"channel": channel, "entrypoint": entrypoint, "amount": amount},
        )
    )


def _setup(tiers=TIERS, tier_version=3):
    alerts = InMemoryAlertRepository()
    rollups = InMemoryMetricsRollupRepository(alerts)
    settings = InMemoryOperationalSettingsRepository(
        OperationalSettings(amount_tiers=list(tiers))
    )
    recorder = RecordAlertMetricsEvent(
        alert_repository=alerts,
        rollup_repository=rollups,
        settings_repository=settings,
        timezone_name=TZ,
        schema_repository=InMemoryAlertSchemaRepository(),
        clock=lambda: NOW,
    )
    return alerts, rollups, settings, recorder


def _event(alert_id, event_type, **fields) -> RecordAlertMetricsEventInput:
    return RecordAlertMetricsEventInput(
        alert_id=alert_id, event_type=event_type, **fields
    )


# --- writer -----------------------------------------------------------------------


def test_created_freezes_canonical_dimensions_and_current_amount_tier() -> None:
    alerts, rollups, settings, recorder = _setup()
    alert = _alert(alerts)

    snapshot = recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.CREATED,
            origin="simulator",
            configuration_id="cfg-1",
        )
    )

    assert snapshot == alerts.get(alert.id).metrics
    assert (snapshot.channel, snapshot.subchannel, snapshot.amount) == (
        "WEB",
        "PSE",
        2_500_000,
    )
    assert (snapshot.amount_tier, snapshot.schema_version) == ("mid", 1)
    assert (snapshot.origin, snapshot.configuration_id) == ("simulator", "cfg-1")
    assert snapshot.mark == Mark.PENDING and snapshot.fraud_label == Mark.PENDING
    assert snapshot.snapshot_version == 1
    assert rollups.total("count", channel="WEB", amount_tier="mid") == 1
    assert rollups.total("count", level=RollupLevel.YEAR) == 1

    # Tier changes later never reclassify this alert.
    settings.settings = OperationalSettings(amount_tiers=[])
    after = recorder.execute(
        _event(alert.id, AlertMetricsEventType.PRE_PROCESSED, segment="s1")
    )
    assert after.amount_tier == "mid"


def test_flat_csv_payload_aliases_and_no_tiers_classify_unknown() -> None:
    alerts, rollups, _, recorder = _setup(tiers=[], tier_version=0)
    alert = _alert(
        alerts,
        {"channel": "APP", "integrationpoint": "BREB", "amount_value": "120000.5"},
    )
    snapshot = recorder.execute(_event(alert.id, AlertMetricsEventType.CREATED))
    assert (snapshot.subchannel, snapshot.amount, snapshot.amount_tier) == (
        "BREB",
        120000.5,
        "unknown",
    )


def test_preprocessed_event_rebases_provisional_metrics_to_canonical_schema() -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    alerts.alerts[alert.id] = dataclasses.replace(alert, schema_version=None, input={})

    provisional = recorder.execute(
        _event(alert.id, AlertMetricsEventType.CREATED, origin="manual")
    )
    assert provisional.schema_version is None
    assert provisional.channel is None

    current = alerts.get(alert.id)
    alerts.alerts[alert.id] = dataclasses.replace(
        current,
        schema_version=1,
        input={"channel": "MOBILE", "entrypoint": "QR", "amount": 1500000},
    )
    canonical = recorder.execute(
        _event(alert.id, AlertMetricsEventType.PRE_PROCESSED, segment="s1")
    )

    assert (canonical.channel, canonical.subchannel, canonical.amount) == (
        "MOBILE",
        "QR",
        1_500_000,
    )
    assert (canonical.amount_tier, canonical.schema_version) == ("mid", 1)
    assert rollups.total("count", channel="unknown") == 0
    assert rollups.total("count", channel="MOBILE", subchannel="QR") == 1


def test_re_recording_the_same_event_is_a_no_op() -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    recorder.execute(_event(alert.id, AlertMetricsEventType.CREATED, origin="manual"))
    finished = _event(
        alert.id,
        AlertMetricsEventType.WORKFLOW_FINISHED,
        status=AlertStatus.CLOSED,
        executed_action="block",
    )
    first = recorder.execute(finished)
    # Celery retry of the same terminal step, a minute later.
    retry = recorder.execute(
        dataclasses.replace(finished, occurred_at=NOW + timedelta(minutes=1))
    )

    assert retry == first
    assert len(rollups.applies) == 2
    assert rollups.total("count") == 1


def test_version_conflict_rereads_and_retries_without_double_counting() -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    recorder.execute(_event(alert.id, AlertMetricsEventType.CREATED, origin="manual"))

    # Another event lands between our read and our write.
    def racing_writer() -> None:
        recorder.execute(
            _event(alert.id, AlertMetricsEventType.PRE_PROCESSED, segment="s1")
        )

    rollups.before_apply.append(racing_writer)
    result = recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.CLOSED,
            executed_action="none",
        )
    )

    assert rollups.conflicts == 1
    assert result.segment == "s1"  # built on the racing writer's snapshot
    assert result.mark == Mark.NO_FRAUD
    assert result.snapshot_version == 3  # created=1, racing=2, ours=3
    assert rollups.total("count") == 1
    assert rollups.total("count", segment="s1", mark="no_fraud") == 1


def test_gives_up_after_max_attempts() -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)

    def bump() -> None:
        current = alerts.get(alert.id)
        version = current.metrics.snapshot_version if current.metrics else 0
        alerts.alerts[alert.id] = dataclasses.replace(
            current, metrics=AlertMetricsSnapshot(snapshot_version=version + 1)
        )

    rollups.before_apply.extend([bump] * MAX_ATTEMPTS)
    with pytest.raises(SnapshotVersionConflictError):
        recorder.execute(_event(alert.id, AlertMetricsEventType.CREATED))
    assert rollups.conflicts == MAX_ATTEMPTS


def test_missing_alert_returns_none() -> None:
    _, rollups, _, recorder = _setup()
    assert recorder.execute(_event(uuid4(), AlertMetricsEventType.CREATED)) is None
    assert rollups.applies == []


# --- D8 mapping through the workflow-finished event ---------------------------------


@pytest.mark.parametrize(
    ("action", "status", "mark", "method"),
    [
        ("block", AlertStatus.CLOSED, Mark.FRAUD, AlertResolutionMethod.ARIA),
        ("none", AlertStatus.CLOSED, Mark.NO_FRAUD, AlertResolutionMethod.ARIA),
        ("discarded", AlertStatus.CLOSED, Mark.NO_FRAUD, AlertResolutionMethod.ARIA),
        ("bidi", AlertStatus.CLOSED, Mark.PENDING, AlertResolutionMethod.BIDI),
        ("voicebot", AlertStatus.CLOSED, Mark.PENDING, AlertResolutionMethod.VOICEBOT),
        (
            "scale_to_analyst",
            AlertStatus.ESCALATED,
            Mark.PENDING,
            AlertResolutionMethod.ANALYST,
        ),
        (None, AlertStatus.FAILED, Mark.PENDING, None),
        (None, AlertStatus.SKIPPED, Mark.PENDING, None),
    ],
)
def test_workflow_finished_maps_decision_to_mark(action, status, mark, method) -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    snapshot = recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=status,
            executed_action=action,
        )
    )
    assert (snapshot.status, snapshot.mark, snapshot.resolution_method) == (
        status,
        mark,
        method,
    )
    assert snapshot.fraud_label == mark
    if mark == Mark.PENDING:
        assert snapshot.marked_at is None and snapshot.resolution_time_seconds is None
    else:
        assert snapshot.marked_at == NOW
        assert snapshot.resolution_time_seconds == 240.0
        assert rollups.total("rt_1_5m") == 1


def test_mark_is_immutable_once_decided() -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.CLOSED,
            executed_action="block",
        )
    )
    later = recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.ANALYST_RESOLVED,
            decision="pass",
            occurred_at=NOW + timedelta(hours=1),
        )
    )
    assert later.mark == Mark.FRAUD
    assert later.resolution_method == AlertResolutionMethod.ARIA
    assert later.marked_at == NOW


def test_fraud_review_event_updates_label_and_counts() -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.CLOSED,
            executed_action="block",
        )
    )
    reviewed_at = NOW + timedelta(days=2)
    snapshot = recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.FRAUD_REVIEWED,
            fraud_label=Mark.NO_FRAUD,
            occurred_at=reviewed_at,
        )
    )
    assert (snapshot.mark, snapshot.fraud_label) == (Mark.FRAUD, Mark.NO_FRAUD)
    assert (
        snapshot.fraud_reviewed_at == reviewed_at and snapshot.fraud_review_count == 1
    )
    # The alert moved rows: the false positive is visible in the rollups.
    assert rollups.total("count", mark="fraud", fraud_label="no_fraud") == 1
    assert rollups.total("count", mark="fraud", fraud_label="fraud") == 0


# --- C4 hook points (API-side use cases) ----------------------------------------------


class RecordingMetricsRecorder:
    def __init__(self) -> None:
        self.events: list[RecordAlertMetricsEventInput] = []

    def execute(self, input: RecordAlertMetricsEventInput):
        self.events.append(input)
        return None


class FailingMetricsRecorder:
    def execute(self, input):
        raise RuntimeError("dynamodb down")


class _Repo:
    """Minimal async-operation / workflow repository + executor fakes."""

    def __init__(self) -> None:
        self.created = []

    def create(self, record):
        self.created.append(record)
        return record

    def update(self, *_args, **_kwargs):
        return None

    def start(self, _workflow):
        return WorkflowExecutionRef(backend="deferred")


def _start_use_case(alerts, metrics):
    repo = _Repo()
    return StartAlertTestWorkflowUseCase(
        alert_repository=alerts,
        async_operation_repository=repo,
        workflow_repository=repo,
        workflow_executor=repo,
        metrics_recorder=metrics,
    )


def test_alert_creation_records_created_event_with_origin_and_pinned_config() -> None:
    alerts, rollups, _, recorder = _setup()
    output = _start_use_case(alerts, recorder).execute(
        StartAlertWorkflowInput(
            payload=PAYLOAD,
            origin=AlertOrigin.TEST_RUN,
            configuration_ref=ConfigurationRef(configuration_id="cfg-7", version=2),
        )
    )
    snapshot = alerts.get(output.alert_id).metrics
    assert snapshot.origin == "test_run"
    assert snapshot.configuration_id == "cfg-7"
    assert snapshot.amount_tier == "unknown"
    assert rollups.total("count", origin="test_run") == 1


def test_alert_creation_survives_a_metrics_failure() -> None:
    alerts = InMemoryAlertRepository()
    output = _start_use_case(alerts, FailingMetricsRecorder()).execute(
        StartAlertWorkflowInput(payload=PAYLOAD)
    )
    assert alerts.get(output.alert_id).status == AlertStatus.PROCESSING


class InMemoryReservations:
    def __init__(self, reservation: ResourceReservation) -> None:
        self.reservation = reservation
        self.released = []

    def list_active(self, resource, now):
        return [self.reservation] if resource == self.reservation.resource else []

    def release(self, reservation_id, *, reason, now, detail=None):
        self.released.append((reservation_id, reason, detail))
        return dataclasses.replace(self.reservation, status=ReservationStatus.RELEASED)


def _reservation(resource: ReservedResource, alert_id: str, holder: str | None = None):
    return ResourceReservation(
        id="r-1",
        resource=resource,
        alert_id=alert_id,
        holder=holder or alert_id,
        slot=0,
        status=ReservationStatus.ACTIVE,
        reserved_at=CREATED_AT,
        expires_at=NOW + timedelta(hours=1),
    )


class RecordingActionDispatcher:
    def __init__(self) -> None:
        self.calls = []

    def dispatch(self, decision, alert_id, content=None):
        self.calls.append((decision, alert_id))
        return AlertActionDispatchRef(backend="mock", external_id="x")


@pytest.mark.parametrize(
    ("decision", "mark", "method"),
    [
        ("block", Mark.FRAUD, AlertResolutionMethod.ANALYST),
        ("pass", Mark.NO_FRAUD, AlertResolutionMethod.ANALYST),
        ("bidi", Mark.PENDING, AlertResolutionMethod.BIDI),
    ],
)
def test_analyst_resolution_records_mark(decision, mark, method) -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.ESCALATED,
            executed_action="scale_to_analyst",
        )
    )
    reservations = InMemoryReservations(
        _reservation(ReservedResource.ANALYST, str(alert.id), holder="ana")
    )
    ResolveEscalatedAlertUseCase(
        alerts,
        reservations,
        RecordingActionDispatcher(),
        clock=lambda: NOW + timedelta(minutes=10),
        metrics_recorder=recorder,
    ).execute(
        ResolveEscalatedAlertInput(
            alert_id=str(alert.id), analyst_id="ana", decision=decision
        )
    )
    snapshot = alerts.get(alert.id).metrics
    assert (snapshot.status, snapshot.mark, snapshot.resolution_method) == (
        AlertStatus.CLOSED,
        mark,
        method,
    )
    if mark != Mark.PENDING:
        assert snapshot.resolution_time_seconds == 14 * 60
    assert rollups.total("count") == 1
    assert rollups.total("count", status="ESCALATED") == 0


@pytest.mark.parametrize(
    ("outcome", "mark"),
    [
        ("fraud_confirmed", Mark.FRAUD),
        ("customer_recognized", Mark.NO_FRAUD),
        ("no_answer", Mark.PENDING),
    ],
)
def test_voicebot_callback_records_mark_from_outcome(outcome, mark) -> None:
    alerts, rollups, _, recorder = _setup()
    alert = _alert(alerts)
    recorder.execute(
        _event(
            alert.id,
            AlertMetricsEventType.WORKFLOW_FINISHED,
            status=AlertStatus.CLOSED,
            executed_action="voicebot",
        )
    )
    reservations = InMemoryReservations(
        _reservation(ReservedResource.VOICEBOT, str(alert.id))
    )
    CompleteVoicebotCallUseCase(
        reservations, clock=lambda: NOW, metrics_recorder=recorder
    ).execute(str(alert.id), outcome)

    snapshot = alerts.get(alert.id).metrics
    assert snapshot.mark == mark
    assert snapshot.resolution_method == AlertResolutionMethod.VOICEBOT
    assert reservations.released  # the business action still happened


def test_voicebot_callback_survives_a_metrics_failure() -> None:
    reservations = InMemoryReservations(
        _reservation(ReservedResource.VOICEBOT, str(uuid4()))
    )
    CompleteVoicebotCallUseCase(
        reservations, clock=lambda: NOW, metrics_recorder=FailingMetricsRecorder()
    ).execute(reservations.reservation.alert_id, "fraud")
    assert reservations.released


# --- T2: dedicated "alert.mark_set" span ----------------------------------------


class RecordingSpan(MonitoringSpan):
    def __init__(self, metadata: dict) -> None:
        self.attributes = dict(metadata)
        self.error: str | None = None
        self.finished = False

    def write_input(self, data): ...
    def write_result(self, data): ...
    def write_inner_logs(self, entries): ...
    def record_dependency(self, name, kind, metadata=None): ...

    def write_operation_metas(self, metadata):
        self.attributes.update(metadata)

    def finish(self, error=None):
        self.error, self.finished = error, True


class RecordingMonitoring(MonitoringPort):
    def __init__(self) -> None:
        self.spans: list[tuple[str, RecordingSpan]] = []

    def start(self, operation_name, operation_type, metadata=None):
        span = RecordingSpan(metadata or {})
        self.spans.append((operation_name, span))
        return span


def test_mark_set_emits_one_span_when_mark_leaves_pending() -> None:
    alerts, rollups, settings, _ = _setup()
    monitoring = RecordingMonitoring()
    recorder = RecordAlertMetricsEvent(
        alert_repository=alerts,
        rollup_repository=rollups,
        settings_repository=settings,
        timezone_name=TZ,
        clock=lambda: NOW,
        monitoring=monitoring,
    )
    alert = _alert(alerts)
    recorder.execute(
        _event(alert.id, AlertMetricsEventType.CREATED, origin="simulator")
    )
    assert monitoring.spans == []  # mark still pending

    finished = _event(
        alert.id,
        AlertMetricsEventType.WORKFLOW_FINISHED,
        status=AlertStatus.CLOSED,
        executed_action="block",
        occurred_at=CREATED_AT + timedelta(minutes=3),
    )
    recorder.execute(finished)
    # A later decision never moves mark again -> no second span.
    recorder.execute(
        _event(alert.id, AlertMetricsEventType.ANALYST_RESOLVED, decision="pass")
    )

    [(name, span)] = monitoring.spans
    assert name == "alert.mark_set" and span.finished and span.error is None
    assert span.attributes["aria.mark"] == "fraud"
    assert span.attributes["aria.resolution_method"] == "aria"
    assert span.attributes["aria.resolution_time_seconds"] == 180.0
    assert span.attributes["aria.channel"] == "WEB"
    assert span.attributes["aria.amount_tier"] == "mid"
    assert span.attributes["aria.origin"] == "simulator"
    # Never the exact amount.
    assert 2_500_000 not in span.attributes.values()
    assert not any("amount" == key.rsplit(".", 1)[-1] for key in span.attributes)
