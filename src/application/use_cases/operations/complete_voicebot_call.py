from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
    ResourceReservationRepository,
)
from src.application.use_cases.analyst_queue.analyst_reservations import (
    active_reservation_for_alert,
)
from src.domain.alerts.exceptions import NoActiveVoicebotCallError


class CompleteVoicebotCallUseCase:
    """The voicebot provider's callback: the call for this alert finished,
    so its slot goes back to the pool. The outcome is kept on the
    reservation record. An alert holds at most one voicebot slot at a time
    (the alert lock), so the alert id identifies the call."""

    def __init__(
        self,
        reservation_repository: ResourceReservationRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._reservations = reservation_repository
        self._clock = clock

    def execute(
        self, alert_id: str, outcome: str, detail: dict[str, Any] | None = None
    ) -> ResourceReservation:
        now = self._clock()
        reservation = active_reservation_for_alert(
            self._reservations, ReservedResource.VOICEBOT, alert_id, now
        )
        if reservation is None:
            raise NoActiveVoicebotCallError(alert_id)
        released = self._reservations.release(
            reservation.id,
            reason="callback",
            now=now,
            detail={"outcome": outcome, **(detail or {})},
        )
        return released or reservation
