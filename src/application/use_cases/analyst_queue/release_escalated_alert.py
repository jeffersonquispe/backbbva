from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
    ResourceReservationRepository,
)
from src.application.use_cases.analyst_queue.analyst_reservations import (
    active_reservation_for_alert,
)
from src.domain.alerts.exceptions import AlertNotHeldByAnalystError


class ReleaseEscalatedAlertUseCase:
    """The analyst gives an alert back without resolving it - it stays
    ESCALATED and returns to the queue for someone else."""

    def __init__(
        self,
        reservation_repository: ResourceReservationRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._reservations = reservation_repository
        self._clock = clock

    def execute(self, alert_id: str, analyst_id: str) -> ResourceReservation:
        now = self._clock()
        reservation = active_reservation_for_alert(
            self._reservations, ReservedResource.ANALYST, alert_id, now
        )
        if reservation is None or reservation.holder != analyst_id:
            raise AlertNotHeldByAnalystError(alert_id)
        released = self._reservations.release(
            reservation.id, reason="released_by_analyst", now=now
        )
        return released or reservation
