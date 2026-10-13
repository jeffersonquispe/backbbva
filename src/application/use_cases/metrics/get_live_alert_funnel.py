"""GetLiveAlertFunnel (R9): the "Tiempo real" funnel - how many alerts are
in each live state right now. Not a rollup (these go up and down): current
counts from the alerts' status index plus the active voicebot calls."""

from __future__ import annotations

from src.application.dtos.metrics_maintenance_dtos import LiveAlertFunnelOutput
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


class GetLiveAlertFunnel:
    def __init__(
        self,
        alert_repository: AlertRepository,
        reservation_repository: ResourceReservationRepository,
        clock: Clock | None = None,
    ) -> None:
        self._alerts = alert_repository
        self._reservations = reservation_repository
        self._clock = resolve_clock(clock)

    def execute(self) -> LiveAlertFunnelOutput:
        now = self._clock.now()
        return LiveAlertFunnelOutput(
            received=self._alerts.count_by_status(AlertStatus.RECEIVED),
            processing=self._alerts.count_by_status(AlertStatus.PROCESSING),
            escalated=self._alerts.count_by_status(AlertStatus.ESCALATED),
            voicebot_in_call=len(
                self._reservations.list_active(ReservedResource.VOICEBOT, now)
            ),
            measured_at=now,
        )
