from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.ports.clock_port import Clock
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
    ResourceReservationRepository,
)
from src.application.runtime_defaults import resolve_clock
from src.application.use_cases.analyst_queue.analyst_reservations import (
    active_reservation_for_alert,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.domain.alerts.exceptions import NoActiveVoicebotCallError

logger = logging.getLogger(__name__)


class CompleteVoicebotCallUseCase:
    """The voicebot provider's callback: the call for this alert finished,
    so its slot goes back to the pool. The outcome is kept on the
    reservation record. An alert holds at most one voicebot slot at a time
    (the alert lock), so the alert id identifies the call."""

    def __init__(
        self,
        reservation_repository: ResourceReservationRepository,
        clock: Clock | None = None,
        metrics_recorder: RecordAlertMetricsEvent | None = None,
    ) -> None:
        self._reservations = reservation_repository
        self._clock = resolve_clock(clock)
        self._metrics = metrics_recorder

    def execute(
        self, alert_id: str, outcome: str, detail: dict[str, Any] | None = None
    ) -> ResourceReservation:
        now = self._clock.now()
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
        self._record_metrics(alert_id, outcome, now)
        return released or reservation

    def _record_metrics(self, alert_id: str, outcome: str, now: datetime) -> None:
        # Best effort, like the analyst resolution: the slot is already
        # released; reconciliation repairs a lost metrics event.
        if self._metrics is None:
            return
        try:
            self._metrics.execute(
                RecordAlertMetricsEventInput(
                    alert_id=UUID(alert_id),
                    event_type=AlertMetricsEventType.VOICEBOT_COMPLETED,
                    occurred_at=now,
                    outcome=outcome,
                )
            )
        except Exception:
            logger.exception("Metrics event failed for alert %s", alert_id)
