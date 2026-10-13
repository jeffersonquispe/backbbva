"""R9 live funnel with in-memory fakes."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from src.application.ports.alert_port import AlertStatus
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
)
from src.application.use_cases.metrics.get_live_alert_funnel import GetLiveAlertFunnel

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)


class CountingAlertRepository:
    def __init__(self, statuses: list[AlertStatus]) -> None:
        self.counts = Counter(statuses)
        self.asked: list[AlertStatus] = []

    def count_by_status(self, status: AlertStatus) -> int:
        self.asked.append(status)
        return self.counts[status]


class InMemoryReservationRepository:
    def __init__(self, active: list[ResourceReservation]) -> None:
        self.active = active
        self.calls: list[tuple[ReservedResource, datetime]] = []

    def list_active(self, resource: ReservedResource, now: datetime) -> list[ResourceReservation]:
        self.calls.append((resource, now))
        return [r for r in self.active if r.resource == resource and r.is_active(now)]


def _reservation(resource: ReservedResource, alert_id: str) -> ResourceReservation:
    return ResourceReservation(
        id=f"r-{alert_id}",
        resource=resource,
        alert_id=alert_id,
        holder=alert_id,
        slot=0,
        reserved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def test_counts_each_live_status_and_active_voicebot_calls():
    alerts = CountingAlertRepository(
        [AlertStatus.RECEIVED] * 2
        + [AlertStatus.PROCESSING] * 5
        + [AlertStatus.ESCALATED] * 3
        + [AlertStatus.CLOSED] * 40
    )
    reservations = InMemoryReservationRepository(
        [
            _reservation(ReservedResource.VOICEBOT, "a1"),
            _reservation(ReservedResource.VOICEBOT, "a2"),
            _reservation(ReservedResource.ANALYST, "a3"),
        ]
    )

    output = GetLiveAlertFunnel(alerts, reservations, clock=lambda: NOW).execute()

    assert (output.received, output.processing, output.escalated, output.voicebot_in_call) == (
        2, 5, 3, 2,
    )
    assert output.measured_at == NOW
    assert set(alerts.asked) == {
        AlertStatus.RECEIVED, AlertStatus.PROCESSING, AlertStatus.ESCALATED,
    }
    assert reservations.calls == [(ReservedResource.VOICEBOT, NOW)]
