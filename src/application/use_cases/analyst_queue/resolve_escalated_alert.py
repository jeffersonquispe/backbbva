from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from src.application.dtos.alert_metrics_dtos import (
    AlertMetricsEventType,
    RecordAlertMetricsEventInput,
)
from src.application.dtos.analyst_queue_dtos import (
    VALID_ANALYST_RESOLUTIONS,
    ResolveEscalatedAlertInput,
)
from src.application.ports.alert_action_dispatcher_port import AlertActionDispatcher
from src.application.ports.alert_port import (
    AlertRepository,
)
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservation,
    ResourceReservationRepository,
)
from src.application.use_cases.analyst_queue.analyst_reservations import (
    active_reservation_for_alert,
)
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.domain.alerts.entities import (
    AlertStatus,
)
from src.domain.alerts.exceptions import AlertNotHeldByAnalystError

logger = logging.getLogger(__name__)


class ResolveEscalatedAlertUseCase:
    """The analyst holding an escalated alert closes it: block/bidi are
    dispatched as channel actions (the notes travel as the ARIC comment),
    pass needs none. The analyst reservation is released with the
    resolution recorded on it, and the alert leaves the queue (CLOSED)."""

    def __init__(
        self,
        alert_repository: AlertRepository,
        reservation_repository: ResourceReservationRepository,
        action_dispatcher: AlertActionDispatcher,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        metrics_recorder: RecordAlertMetricsEvent | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._reservations = reservation_repository
        self._actions = action_dispatcher
        self._clock = clock
        self._metrics = metrics_recorder

    def execute(self, input: ResolveEscalatedAlertInput) -> ResourceReservation:
        if input.decision not in VALID_ANALYST_RESOLUTIONS:
            raise ValueError(f"Unsupported resolution: {input.decision}")
        now = self._clock()
        reservation = active_reservation_for_alert(
            self._reservations, ReservedResource.ANALYST, input.alert_id, now
        )
        if reservation is None or reservation.holder != input.analyst_id:
            raise AlertNotHeldByAnalystError(input.alert_id)

        detail: dict[str, object] = {
            "decision": input.decision,
            "notes": input.notes,
            "resolved_by": input.analyst_id,
        }
        if input.decision != "pass":
            ref = self._actions.dispatch(
                input.decision, UUID(input.alert_id), content=input.notes or None
            )
            detail["dispatch_backend"] = ref.backend
            detail["dispatch_external_id"] = ref.external_id
        released = self._reservations.release(
            reservation.id, reason="resolved", now=now, detail=detail
        )
        self._alerts.update(UUID(input.alert_id), status=AlertStatus.CLOSED)
        self._record_metrics(input, now)
        return released or reservation

    def _record_metrics(self, input: ResolveEscalatedAlertInput, now: datetime) -> None:
        # Best effort: the resolution already happened; a metrics failure
        # is repaired by the daily reconciliation, never surfaced here.
        if self._metrics is None:
            return
        try:
            self._metrics.execute(
                RecordAlertMetricsEventInput(
                    alert_id=UUID(input.alert_id),
                    event_type=AlertMetricsEventType.ANALYST_RESOLVED,
                    occurred_at=now,
                    decision=input.decision,
                )
            )
        except Exception:
            logger.exception("Metrics event failed for alert %s", input.alert_id)
