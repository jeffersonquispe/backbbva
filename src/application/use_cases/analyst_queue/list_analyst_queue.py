from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from src.application.dtos.analyst_queue_dtos import AnalystQueueItem
from src.application.ports.alert_port import AlertRepository, AlertStatus
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservationRepository,
)


class ListAnalystQueueUseCase:
    """Escalated alerts waiting for a human, oldest first, each with the
    analyst currently holding it (if any)."""

    def __init__(
        self,
        alert_repository: AlertRepository,
        reservation_repository: ResourceReservationRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._alerts = alert_repository
        self._reservations = reservation_repository
        self._clock = clock

    def execute(self) -> list[AnalystQueueItem]:
        now = self._clock()
        held = {
            reservation.alert_id: reservation
            for reservation in self._reservations.list_active(
                ReservedResource.ANALYST, now
            )
        }
        return [
            AnalystQueueItem(alert=alert, reservation=held.get(str(alert.id)))
            for alert in self._alerts.list_by_status(AlertStatus.ESCALATED)
        ]
