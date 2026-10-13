"""RecordOperationalState: the 60 s operational-gauge sample, with fakes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.configuration_port import AnalystCapacity, DayProfile
from src.application.ports.monitoring_port import (
    MonitoringPort,
    OperationalStateSnapshot,
)
from src.application.ports.operational_settings_port import OperationalSettings
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.application.use_cases.metrics.record_operational_state import (
    RecordOperationalState,
)

TZ = "America/Bogota"
# 15:00 UTC = 10:00 Bogota, on the 1st (no day override -> "regular").
NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)


def _staffing(hour_10: int) -> AnalystCapacity:
    hourly = [0] * 24
    hourly[10] = hour_10
    return AnalystCapacity(
        profiles=[DayProfile("regular", "Regular", "", hourly)],
        default_profile_id="regular",
        day_overrides={},
    )


class InMemorySettings:
    def __init__(self, settings: OperationalSettings) -> None:
        self.settings = settings

    def get(self) -> OperationalSettings:
        return self.settings


class InMemoryAlertRepository:
    def __init__(self, alerts: list[AlertRecord]) -> None:
        self.alerts = alerts
        self.list_calls = 0

    def count_by_status(self, status: AlertStatus) -> int:
        return sum(1 for a in self.alerts if a.status == status)

    def list_by_status(self, status: AlertStatus) -> list[AlertRecord]:
        self.list_calls += 1
        return sorted(
            (a for a in self.alerts if a.status == status), key=lambda a: a.created_at
        )


class FixedCapacity(OperationsCapacityPort):
    def __init__(self, analysts: int, voicebot: int) -> None:
        self._record = OperationsCapacityRecord(
            analysts=ChannelCapacity(analysts, "available"),
            voicebot=ChannelCapacity(voicebot, "available"),
            bidi=ChannelCapacity(0, "unavailable"),
            updated_at=NOW,
        )

    def get_capacity(self) -> OperationsCapacityRecord:
        return self._record


class RecordingMonitoring(MonitoringPort):
    def __init__(self) -> None:
        self.states: list[OperationalStateSnapshot] = []

    def start(self, operation_name, operation_type, metadata=None):
        raise AssertionError("no spans expected")

    def record_operational_state(self, snapshot) -> None:
        self.states.append(snapshot)


def _alert(status: AlertStatus, age_minutes: float) -> AlertRecord:
    created = NOW - timedelta(minutes=age_minutes)
    return AlertRecord(
        id=uuid4(),
        event_id="e",
        event_type="payment",
        input={},
        status=status,
        created_at=created,
        updated_at=created,
    )


def _use_case(settings, alerts, capacity, monitoring):
    return RecordOperationalState(
        settings_repository=InMemorySettings(settings),
        alert_repository=alerts,
        operations_capacity=capacity,
        monitoring=monitoring,
        timezone_name=TZ,
        clock=lambda: NOW,
    )


def test_samples_agent_hours_queue_and_capacity() -> None:
    alerts = InMemoryAlertRepository(
        [
            _alert(AlertStatus.ESCALATED, 5),
            _alert(AlertStatus.ESCALATED, 20),
            _alert(AlertStatus.CLOSED, 90),
        ]
    )
    monitoring = RecordingMonitoring()

    snapshot = _use_case(
        OperationalSettings(agent_enabled=True, analyst_capacity=_staffing(4)),
        alerts,
        FixedCapacity(analysts=3, voicebot=12),
        monitoring,
    ).execute()

    assert monitoring.states == [snapshot]
    assert snapshot == OperationalStateSnapshot(
        agent_enabled=True,
        within_operating_hours=True,
        analyst_queue_depth=2,
        analyst_queue_oldest_age_seconds=20 * 60.0,
        analysts_available=3,
        voicebot_slots_available=12,
    )


def test_empty_queue_and_unstaffed_hour() -> None:
    alerts = InMemoryAlertRepository([_alert(AlertStatus.CLOSED, 90)])
    monitoring = RecordingMonitoring()

    snapshot = _use_case(
        OperationalSettings(agent_enabled=False, analyst_capacity=_staffing(0)),
        alerts,
        FixedCapacity(analysts=0, voicebot=0),
        monitoring,
    ).execute()

    assert snapshot.agent_enabled is False
    assert snapshot.within_operating_hours is False
    assert (
        snapshot.analyst_queue_depth,
        snapshot.analyst_queue_oldest_age_seconds,
    ) == (0, 0.0)
    # The live counter said 0: the queue is never listed.
    assert alerts.list_calls == 0
