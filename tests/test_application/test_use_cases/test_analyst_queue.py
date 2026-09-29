from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.application.dtos.analyst_queue_dtos import ResolveEscalatedAlertInput
from src.application.ports.alert_action_dispatcher_port import (
    AlertActionDispatcher,
    AlertActionDispatchRef,
)
from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.application.ports.resource_reservation_port import (
    RESERVATION_TTL,
    AcquireResult,
    ReservationConflict,
    ReservationStatus,
    ReservedResource,
    ResourceReservation,
)
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.application.use_cases.analyst_queue.get_alert_detail import (
    GetAlertDetailUseCase,
)
from src.application.use_cases.analyst_queue.list_analyst_queue import (
    ListAnalystQueueUseCase,
)
from src.application.use_cases.analyst_queue.release_escalated_alert import (
    ReleaseEscalatedAlertUseCase,
)
from src.application.use_cases.analyst_queue.resolve_escalated_alert import (
    ResolveEscalatedAlertUseCase,
)
from src.application.use_cases.analyst_queue.take_escalated_alert import (
    TakeEscalatedAlertUseCase,
)
from src.application.use_cases.operations.complete_voicebot_call import (
    CompleteVoicebotCallUseCase,
)
from src.domain.alerts.exceptions import (
    AlertAlreadyTakenError,
    AlertNotFoundError,
    AlertNotHeldByAnalystError,
    AlertNotInAnalystQueueError,
    AnalystBusyError,
    NoActiveVoicebotCallError,
    NoAnalystCapacityError,
)

NOW = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)


class InMemoryResourceReservationRepository:
    def __init__(self) -> None:
        self.records: dict[str, ResourceReservation] = {}

    def _active(self, resource, now):
        return [
            r for r in self.records.values() if r.resource == resource and r.is_active(now)
        ]

    def try_acquire(self, resource, *, alert_id, holder, capacity, now, ttl=RESERVATION_TTL):
        active = self._active(resource, now)
        if any(r.alert_id == alert_id for r in active):
            return AcquireResult(None, ReservationConflict.ALERT_TAKEN)
        if holder != alert_id and any(r.holder == holder for r in active):
            return AcquireResult(None, ReservationConflict.HOLDER_BUSY)
        used = {r.slot for r in active}
        free = [slot for slot in range(capacity) if slot not in used]
        if not free:
            return AcquireResult(None, ReservationConflict.NO_CAPACITY)
        reservation = ResourceReservation(
            id=str(uuid.uuid4()),
            resource=resource,
            alert_id=alert_id,
            holder=holder,
            slot=free[0],
            reserved_at=now,
            expires_at=now + ttl,
        )
        self.records[reservation.id] = reservation
        return AcquireResult(reservation)

    def release(self, reservation_id, *, reason, now, detail=None):
        reservation = self.records.get(reservation_id)
        if reservation is None or reservation.status != ReservationStatus.ACTIVE:
            return reservation
        reservation.status = ReservationStatus.RELEASED
        reservation.released_at = now
        reservation.release_reason = reason
        reservation.detail = {**reservation.detail, **(detail or {})}
        return reservation

    def get(self, reservation_id):
        return self.records.get(reservation_id)

    def list_active(self, resource, now):
        return self._active(resource, now)


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self.alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    def update(self, alert_id: UUID, *, status=None, **_) -> AlertRecord | None:
        alert = self.alerts.get(alert_id)
        if alert is not None and status is not None:
            alert.status = status
        return alert

    def list_by_status(self, status: AlertStatus) -> list[AlertRecord]:
        return sorted(
            (a for a in self.alerts.values() if a.status == status),
            key=lambda a: a.created_at,
        )


class FixedAnalystCapacity(OperationsCapacityPort):
    def __init__(self, total: int, status: str = "available") -> None:
        self._analysts = ChannelCapacity(available=total, status=status, total=total)

    def get_capacity(self) -> OperationsCapacityRecord:
        other = ChannelCapacity(available=0, status="unavailable")
        return OperationsCapacityRecord(
            analysts=self._analysts, voicebot=other, bidi=other, updated_at=NOW
        )


class RecordingAlertActionDispatcher(AlertActionDispatcher):
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, str | None]] = []

    def dispatch(self, action, alert_id, content=None) -> AlertActionDispatchRef:
        self.calls.append((action, alert_id, content))
        return AlertActionDispatchRef(backend="celery", external_id="task-1")


def _alert(alerts: InMemoryAlertRepository, status=AlertStatus.ESCALATED, minutes_ago=0):
    created = NOW - timedelta(minutes=minutes_ago)
    return alerts.create(
        AlertRecord(
            id=uuid.uuid4(),
            event_id="evt",
            event_type="paymentRT",
            payload={"amount": 100},
            status=status,
            created_at=created,
            updated_at=created,
        )
    )


def _take(alerts, reservations, total=2, status="available"):
    return TakeEscalatedAlertUseCase(
        alerts, reservations, FixedAnalystCapacity(total, status), clock=lambda: NOW
    )


# --- take ------------------------------------------------------------------


def test_take_reserves_the_alert_for_the_analyst_for_30_minutes() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    alert = _alert(alerts)

    reservation = _take(alerts, reservations).execute(alert.id, "analyst-1")

    assert reservation.resource == ReservedResource.ANALYST
    assert reservation.alert_id == str(alert.id)
    assert reservation.holder == "analyst-1"
    assert reservation.expires_at == NOW + timedelta(minutes=30)


def test_taking_the_alert_you_already_hold_returns_the_same_reservation() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    alert = _alert(alerts)
    take = _take(alerts, reservations)
    first = take.execute(alert.id, "analyst-1")

    assert take.execute(alert.id, "analyst-1").id == first.id


def test_an_analyst_holds_at_most_one_alert() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    first, second = _alert(alerts), _alert(alerts)
    take = _take(alerts, reservations)
    take.execute(first.id, "analyst-1")

    with pytest.raises(AnalystBusyError) as exc:
        take.execute(second.id, "analyst-1")

    assert exc.value.held_alert_id == str(first.id)


def test_an_alert_has_at_most_one_analyst() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    alert = _alert(alerts)
    take = _take(alerts, reservations)
    take.execute(alert.id, "analyst-1")

    with pytest.raises(AlertAlreadyTakenError):
        take.execute(alert.id, "analyst-2")


def test_take_respects_the_matrix_quota_for_this_hour() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    take = _take(alerts, reservations, total=1)
    take.execute(_alert(alerts).id, "analyst-1")

    with pytest.raises(NoAnalystCapacityError):
        take.execute(_alert(alerts).id, "analyst-2")


def test_take_fails_while_analysts_are_switched_off() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()

    with pytest.raises(NoAnalystCapacityError):
        _take(alerts, reservations, total=5, status="unavailable").execute(
            _alert(alerts).id, "analyst-1"
        )


def test_an_expired_reservation_frees_the_alert_for_another_analyst() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    alert = _alert(alerts)
    TakeEscalatedAlertUseCase(
        alerts,
        reservations,
        FixedAnalystCapacity(2),
        clock=lambda: NOW - timedelta(minutes=31),
    ).execute(alert.id, "analyst-1")

    reservation = _take(alerts, reservations).execute(alert.id, "analyst-2")

    assert reservation.holder == "analyst-2"


@pytest.mark.parametrize("status", [AlertStatus.CLOSED, AlertStatus.PROCESSING])
def test_only_escalated_alerts_can_be_taken(status) -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()

    with pytest.raises(AlertNotInAnalystQueueError):
        _take(alerts, reservations).execute(_alert(alerts, status=status).id, "analyst-1")


def test_take_unknown_alert_raises() -> None:
    with pytest.raises(AlertNotFoundError):
        _take(InMemoryAlertRepository(), InMemoryResourceReservationRepository()).execute(
            uuid.uuid4(), "analyst-1"
        )


# --- resolve / release -------------------------------------------------------


def _resolve(alerts, reservations, dispatcher):
    return ResolveEscalatedAlertUseCase(alerts, reservations, dispatcher, clock=lambda: NOW)


def test_resolve_dispatches_the_action_closes_the_alert_and_frees_the_analyst() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    dispatcher = RecordingAlertActionDispatcher()
    alert = _alert(alerts)
    _take(alerts, reservations).execute(alert.id, "analyst-1")

    released = _resolve(alerts, reservations, dispatcher).execute(
        ResolveEscalatedAlertInput(
            alert_id=str(alert.id),
            analyst_id="analyst-1",
            decision="block",
            notes="Cliente confirmó fraude",
        )
    )

    assert dispatcher.calls == [("block", alert.id, "Cliente confirmó fraude")]
    assert alerts.get(alert.id).status == AlertStatus.CLOSED
    assert released.status == ReservationStatus.RELEASED
    assert released.release_reason == "resolved"
    assert released.detail["decision"] == "block"
    assert released.detail["resolved_by"] == "analyst-1"
    assert reservations.list_active(ReservedResource.ANALYST, NOW) == []


def test_resolve_pass_dispatches_nothing() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    dispatcher = RecordingAlertActionDispatcher()
    alert = _alert(alerts)
    _take(alerts, reservations).execute(alert.id, "analyst-1")

    _resolve(alerts, reservations, dispatcher).execute(
        ResolveEscalatedAlertInput(alert_id=str(alert.id), analyst_id="analyst-1", decision="pass")
    )

    assert dispatcher.calls == []
    assert alerts.get(alert.id).status == AlertStatus.CLOSED


def test_only_the_holder_can_resolve() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    dispatcher = RecordingAlertActionDispatcher()
    alert = _alert(alerts)
    _take(alerts, reservations).execute(alert.id, "analyst-1")

    with pytest.raises(AlertNotHeldByAnalystError):
        _resolve(alerts, reservations, dispatcher).execute(
            ResolveEscalatedAlertInput(
                alert_id=str(alert.id), analyst_id="analyst-2", decision="block"
            )
        )

    assert dispatcher.calls == []
    assert alerts.get(alert.id).status == AlertStatus.ESCALATED


def test_release_returns_the_alert_to_the_queue() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    alert = _alert(alerts)
    _take(alerts, reservations).execute(alert.id, "analyst-1")

    released = ReleaseEscalatedAlertUseCase(reservations, clock=lambda: NOW).execute(
        str(alert.id), "analyst-1"
    )

    assert released.release_reason == "released_by_analyst"
    assert alerts.get(alert.id).status == AlertStatus.ESCALATED
    # Someone else can take it now.
    assert _take(alerts, reservations).execute(alert.id, "analyst-2").holder == "analyst-2"


def test_release_requires_holding_the_alert() -> None:
    with pytest.raises(AlertNotHeldByAnalystError):
        ReleaseEscalatedAlertUseCase(
            InMemoryResourceReservationRepository(), clock=lambda: NOW
        ).execute("a1", "analyst-1")


# --- list / detail -----------------------------------------------------------


def test_list_shows_escalated_alerts_oldest_first_with_their_holder() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    newer = _alert(alerts, minutes_ago=1)
    older = _alert(alerts, minutes_ago=10)
    _alert(alerts, status=AlertStatus.CLOSED)
    _take(alerts, reservations).execute(newer.id, "analyst-1")

    items = ListAnalystQueueUseCase(alerts, reservations, clock=lambda: NOW).execute()

    assert [item.alert.id for item in items] == [older.id, newer.id]
    assert items[0].reservation is None
    assert items[1].reservation.holder == "analyst-1"


class InMemoryWorkflowRepository:
    def __init__(self, workflow: WorkflowExecutionRecord) -> None:
        self._workflow = workflow

    def get(self, workflow_id):
        return self._workflow if workflow_id == self._workflow.id else None


class InMemoryStepRepository:
    def __init__(self, steps: list[WorkflowStepExecutionRecord]) -> None:
        self._steps = steps

    def list_by_workflow(self, workflow_execution_id):
        return [s for s in self._steps if s.workflow_execution_id == workflow_execution_id]


def test_detail_includes_the_workflow_steps_and_holder() -> None:
    alerts, reservations = InMemoryAlertRepository(), InMemoryResourceReservationRepository()
    alert = _alert(alerts)
    workflow = WorkflowExecutionRecord(
        id=uuid.uuid4(),
        alert_id=alert.id,
        async_operation_id=uuid.uuid4(),
        workflow_name="alert_review",
        status=WorkflowStatus.SUCCEEDED,
        input={},
        output={"status": "success"},
        error=None,
        current_step="post_process",
        feedback_iterations=0,
        max_feedback_iterations=1,
        created_at=NOW,
        updated_at=NOW,
    )
    alert.workflow_execution_id = workflow.id
    step = WorkflowStepExecutionRecord(
        id=uuid.uuid4(),
        workflow_execution_id=workflow.id,
        step_name="analyst",
        status=WorkflowStepStatus.SUCCEEDED,
        attempt=1,
        input={},
        output={"decision": "scale_to_analyst"},
        error=None,
        started_at=NOW,
        finished_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    _take(alerts, reservations).execute(alert.id, "analyst-1")

    detail = GetAlertDetailUseCase(
        alerts,
        reservations,
        InMemoryWorkflowRepository(workflow),
        InMemoryStepRepository([step]),
        clock=lambda: NOW,
    ).execute(alert.id)

    assert detail.alert.id == alert.id
    assert detail.workflow.id == workflow.id
    assert [s.step_name for s in detail.steps] == ["analyst"]
    assert detail.reservation.holder == "analyst-1"


# --- voicebot callback -------------------------------------------------------


def test_voicebot_callback_frees_the_alerts_slot_and_keeps_the_outcome() -> None:
    reservations = InMemoryResourceReservationRepository()
    reservations.try_acquire(
        ReservedResource.VOICEBOT, alert_id="a1", holder="a1", capacity=1, now=NOW
    )

    released = CompleteVoicebotCallUseCase(reservations, clock=lambda: NOW).execute(
        "a1", "confirmed_by_customer", {"duration_s": 42}
    )

    assert released.status == ReservationStatus.RELEASED
    assert released.release_reason == "callback"
    assert released.detail == {"outcome": "confirmed_by_customer", "duration_s": 42}
    assert reservations.list_active(ReservedResource.VOICEBOT, NOW) == []


def test_voicebot_callback_without_an_active_call_raises() -> None:
    reservations = InMemoryResourceReservationRepository()
    # Expired before the callback arrived.
    reservations.try_acquire(
        ReservedResource.VOICEBOT,
        alert_id="a1",
        holder="a1",
        capacity=1,
        now=NOW - timedelta(minutes=45),
    )

    with pytest.raises(NoActiveVoicebotCallError):
        CompleteVoicebotCallUseCase(reservations, clock=lambda: NOW).execute("a1", "late")
