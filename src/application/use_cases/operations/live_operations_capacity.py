from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.application.ports.resource_reservation_port import (
    ReservedResource,
    ResourceReservationRepository,
)
from src.domain.configurations.entities import (
    AnalystCapacity,
)


def analysts_scheduled(capacity: AnalystCapacity, local_now: datetime) -> int:
    """How many analysts the staffing matrix plans for this exact hour: the
    day-of-month override's profile if there is one, else the default
    profile, indexed by the local hour."""
    profile_id = capacity.day_overrides.get(local_now.day, capacity.default_profile_id)
    profile = next((p for p in capacity.profiles if p.id == profile_id), None)
    if profile is None or len(profile.hourly) <= local_now.hour:
        return 0
    return max(int(profile.hourly[local_now.hour]), 0)


def _channel(enabled: bool, total: int, reserved: int) -> ChannelCapacity:
    if not enabled:
        return ChannelCapacity(available=0, status="unavailable", total=0)
    available = max(total - reserved, 0)
    return ChannelCapacity(
        available=available,
        status="available" if available > 0 else "exhausted",
        total=total,
    )


class LiveOperationsCapacity(OperationsCapacityPort):
    """Availability computed on demand, never stored:

    - analysts: the staffing matrix value for the current local hour, minus
      analysts currently holding an alert (reservations in the ANALYST pool).
    - voicebot: the fixed slot quota, minus calls waiting on a callback.
    - either one reads 0 / "unavailable" while switched off in
      OperationalSettings.
    - bidi: not modelled yet - passed through from the static snapshot.
    """

    def __init__(
        self,
        settings_repository: OperationalSettingsRepository,
        reservation_repository: ResourceReservationRepository,
        static_capacity: OperationsCapacityPort,
        timezone_name: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings_repository
        self._reservations = reservation_repository
        self._static = static_capacity
        self._timezone = ZoneInfo(timezone_name)
        self._clock = clock

    def get_capacity(self) -> OperationsCapacityRecord:
        now = self._clock()
        settings = self._settings.get()
        analysts = _channel(
            settings.analyst_enabled,
            analysts_scheduled(
                settings.analyst_capacity, now.astimezone(self._timezone)
            ),
            len(self._reservations.list_active(ReservedResource.ANALYST, now)),
        )
        voicebot = _channel(
            settings.voicebot_enabled,
            settings.voicebot_max_concurrent_calls,
            len(self._reservations.list_active(ReservedResource.VOICEBOT, now)),
        )
        return OperationsCapacityRecord(
            analysts=analysts,
            voicebot=voicebot,
            bidi=self._static.get_capacity().bidi,
            updated_at=now,
        )
