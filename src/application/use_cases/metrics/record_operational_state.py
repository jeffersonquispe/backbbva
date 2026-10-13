"""RecordOperationalState (T3/T5): one sample of the operational gauges,
taken by a Celery Beat tick (metrics.record_operational_state, every 60 s).

Feeds the "stuck queue", "no capacity" and "dead man's switch" alert rules:

- agent ON/OFF            <- OperationalSettings.agent_enabled
- within operating hours  <- the analyst staffing matrix plans > 0 analysts
                             for the current local hour (the same matrix
                             LiveOperationsCapacity reads); there is no other
                             "operating hours" setting
- analyst queue depth     <- live ESCALATED count (status index, R9 - the
                             same counter as the live funnel)
- oldest queued age       <- now - created_at of the oldest ESCALATED alert
                             (only listed when the queue is non-empty)
- analysts / voicebot     <- LiveOperationsCapacity's available slots
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.application.ports.alert_port import AlertRepository, AlertStatus
from src.application.ports.monitoring_port import (
    MonitoringPort,
    OperationalStateSnapshot,
)
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.ports.operations_capacity_port import OperationsCapacityPort
from src.application.use_cases.operations.live_operations_capacity import (
    analysts_scheduled,
)


class RecordOperationalState:
    def __init__(
        self,
        settings_repository: OperationalSettingsRepository,
        alert_repository: AlertRepository,
        operations_capacity: OperationsCapacityPort,
        monitoring: MonitoringPort,
        timezone_name: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings_repository
        self._alerts = alert_repository
        self._capacity = operations_capacity
        self._monitoring = monitoring
        self._timezone = ZoneInfo(timezone_name)
        self._clock = clock

    def execute(self) -> OperationalStateSnapshot:
        now = self._clock()
        settings = self._settings.get()
        depth = self._alerts.count_by_status(AlertStatus.ESCALATED)
        oldest_age = 0.0
        if depth > 0:
            queued = self._alerts.list_by_status(AlertStatus.ESCALATED)
            if queued:
                oldest = min(alert.created_at for alert in queued)
                oldest_age = max((now - oldest).total_seconds(), 0.0)
        capacity = self._capacity.get_capacity()
        snapshot = OperationalStateSnapshot(
            agent_enabled=settings.agent_enabled,
            within_operating_hours=analysts_scheduled(
                settings.analyst_capacity, now.astimezone(self._timezone)
            )
            > 0,
            analyst_queue_depth=depth,
            analyst_queue_oldest_age_seconds=oldest_age,
            analysts_available=capacity.analysts.available,
            voicebot_slots_available=capacity.voicebot.available,
        )
        self._monitoring.record_operational_state(snapshot)
        return snapshot
