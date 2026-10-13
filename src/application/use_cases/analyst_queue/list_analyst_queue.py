from __future__ import annotations

from src.application.dtos.analyst_queue_dtos import AnalystQueueItem
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.clock_port import Clock
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservationRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.domain.alerts.entities import (
    AlertStatus,
)


class ListAnalystQueueUseCase:
    """Escalated alerts waiting for a human, oldest first, each with the
    analyst currently holding it (if any)."""

    def __init__(
        self,
        alert_repository: AlertRepository,
        reservation_repository: ResourceReservationRepository,
        clock: Clock | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._reservations = reservation_repository
        self._clock = resolve_clock(clock)

    def execute(self) -> list[AnalystQueueItem]:
        now = self._clock.now()
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
