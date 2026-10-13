from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from src.application.ports.alert_port import AlertRepository, AlertStatus
from src.application.ports.operations_capacity_port import OperationsCapacityPort
from src.application.ports.resource_reservation_port import (
    ReservationConflict,
    ReservedResource,
    ResourceReservation,
    ResourceReservationRepository,
)
from src.application.use_cases.analyst_queue.analyst_reservations import (
    active_reservation_for_alert,
    active_reservation_for_holder,
)
from src.domain.alerts.exceptions import (
    AlertAlreadyTakenError,
    AlertNotFoundError,
    AlertNotInAnalystQueueError,
    AnalystBusyError,
    NoAnalystCapacityError,
)


class TakeEscalatedAlertUseCase:
    """An analyst starts working on an escalated alert: reserves one of the
    analysts the staffing matrix plans for this hour (30-minute TTL). One
    alert per analyst, one analyst per alert - the reservation's holder and
    alert locks enforce both atomically. Taking the alert you already hold
    is a no-op that returns your reservation."""

    def __init__(
        self,
        alert_repository: AlertRepository,
        reservation_repository: ResourceReservationRepository,
        operations_capacity: OperationsCapacityPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._alerts = alert_repository
        self._reservations = reservation_repository
        self._capacity = operations_capacity
        self._clock = clock

    def execute(self, alert_id: UUID, analyst_id: str) -> ResourceReservation:
        alert = self._alerts.get(alert_id)
        if alert is None:
            raise AlertNotFoundError(str(alert_id))
        if alert.status != AlertStatus.ESCALATED:
            raise AlertNotInAnalystQueueError(str(alert_id), alert.status.value)

        now = self._clock()
        current = active_reservation_for_alert(
            self._reservations, ReservedResource.ANALYST, str(alert_id), now
        )
        if current is not None and current.holder == analyst_id:
            return current

        analysts = self._capacity.get_capacity().analysts
        # The quota is the matrix value for this hour (0 while switched off);
        # try_acquire subtracts the analysts already holding an alert.
        total = 0 if analysts.status == "unavailable" else (analysts.total or 0)
        result = self._reservations.try_acquire(
            ReservedResource.ANALYST,
            alert_id=str(alert_id),
            holder=analyst_id,
            capacity=total,
            now=now,
        )
        if result.reservation is not None:
            return result.reservation
        if result.conflict == ReservationConflict.HOLDER_BUSY:
            held = active_reservation_for_holder(
                self._reservations, ReservedResource.ANALYST, analyst_id, now
            )
            raise AnalystBusyError(held.alert_id if held is not None else None)
        if result.conflict == ReservationConflict.ALERT_TAKEN:
            raise AlertAlreadyTakenError(str(alert_id))
        raise NoAnalystCapacityError()
