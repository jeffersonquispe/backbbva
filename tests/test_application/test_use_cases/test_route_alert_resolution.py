from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.application.ports.configuration_port import (
    AnalystCapacity,
    DayProfile,
    ResolutionTag,
    ShortageBehavior,
)
from src.application.ports.modus_operandi_library_port import ModusOperandiPlaybook
from src.application.ports.operational_settings_port import OperationalSettings
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.application.ports.resource_reservation_port import (
    RESERVATION_TTL,
    AcquireResult,
    ReservationConflict,
    ReservationStatus,
    ReservedResource,
    ResourceReservation,
)
from src.application.use_cases.alerts.route_alert_resolution import (
    FallbackStep,
    RouteAlertResolutionUseCase,
)
from src.application.use_cases.operations.live_operations_capacity import (
    LiveOperationsCapacity,
    analysts_scheduled,
)

# 2026-09-15 14:30 in Bogotá (UTC-5) - day 15, hour 14.
NOW = datetime(2026, 9, 15, 19, 30, tzinfo=UTC)


class InMemoryResourceReservationRepository:
    """Same contract as DynamoResourceReservationRepository: slots in
    [0, capacity), one holder per alert, one alert per holder, expiry."""

    def __init__(self) -> None:
        self.records: dict[str, ResourceReservation] = {}

    def _active(self, resource, now):
        return [
            r
            for r in self.records.values()
            if r.resource == resource and r.is_active(now)
        ]

    def try_acquire(
        self, resource, *, alert_id, holder, capacity, now, ttl=RESERVATION_TTL
    ):
        active = self._active(resource, now)
        if any(r.alert_id == alert_id for r in active):
            return AcquireResult(None, ReservationConflict.ALERT_TAKEN)
        if holder != alert_id and any(r.holder == holder for r in active):
            return AcquireResult(None, ReservationConflict.HOLDER_BUSY)
        used = {r.slot for r in active}
        free = [slot for slot in range(capacity) if slot not in used]
        if not free:
            return AcquireResult(None, ReservationConflict.NO_CAPACITY)
        reservation = ResourceReservation(
            id=str(uuid.uuid4()),
            resource=resource,
            alert_id=alert_id,
            holder=holder,
            slot=free[0],
            reserved_at=now,
            expires_at=now + ttl,
        )
        self.records[reservation.id] = reservation
        return AcquireResult(reservation)

    def release(self, reservation_id, *, reason, now, detail=None):
        reservation = self.records.get(reservation_id)
        if reservation is None or reservation.status != ReservationStatus.ACTIVE:
            return reservation
        reservation.status = ReservationStatus.RELEASED
        reservation.released_at = now
        reservation.release_reason = reason
        reservation.detail = {**reservation.detail, **(detail or {})}
        return reservation

    def get(self, reservation_id):
        return self.records.get(reservation_id)

    def list_active(self, resource, now):
        return self._active(resource, now)


class InMemoryOperationalSettingsRepository:
    def __init__(self, settings: OperationalSettings) -> None:
        self.settings = settings

    def get(self) -> OperationalSettings:
        return self.settings


class StaticBidiCapacity(OperationsCapacityPort):
    def get_capacity(self) -> OperationsCapacityRecord:
        unused = ChannelCapacity(available=0, status="unavailable")
        return OperationsCapacityRecord(
            analysts=unused,
            voicebot=unused,
            bidi=ChannelCapacity(available=7, status="available"),
            updated_at=NOW,
        )


def _matrix(regular: int = 4, payday: int = 8) -> AnalystCapacity:
    return AnalystCapacity(
        profiles=[
            DayProfile(
                id="regular", name="Regular", description="", hourly=[regular] * 24
            ),
            DayProfile(id="pago", name="Pago", description="", hourly=[payday] * 24),
        ],
        default_profile_id="regular",
        day_overrides={15: "pago"},
    )


def _capacity(settings: OperationalSettings, reservations) -> LiveOperationsCapacity:
    return LiveOperationsCapacity(
        settings_repository=InMemoryOperationalSettingsRepository(settings),
        reservation_repository=reservations,
        static_capacity=StaticBidiCapacity(),
        timezone_name="America/Bogota",
        clock=lambda: NOW,
    )


# --- LiveOperationsCapacity ------------------------------------------------


def test_analysts_scheduled_reads_the_day_override_profile_at_the_local_hour() -> None:
    capacity = _matrix()
    capacity.profiles[1].hourly[14] = 6

    local = NOW.astimezone(ZoneInfo("America/Bogota"))

    assert (local.day, local.hour) == (15, 14)
    assert analysts_scheduled(capacity, local) == 6
    assert analysts_scheduled(capacity, local.replace(day=16)) == 4


def test_live_capacity_subtracts_active_reservations_from_matrix_and_slots() -> None:
    reservations = InMemoryResourceReservationRepository()
    reservations.try_acquire(
        ReservedResource.ANALYST, alert_id="a1", holder="u1", capacity=8, now=NOW
    )
    reservations.try_acquire(
        ReservedResource.VOICEBOT, alert_id="a2", holder="a2", capacity=3, now=NOW
    )
    # Expired - no longer counts.
    reservations.try_acquire(
        ReservedResource.VOICEBOT,
        alert_id="a3",
        holder="a3",
        capacity=3,
        now=NOW - timedelta(hours=1),
    )
    settings = OperationalSettings(
        voicebot_max_concurrent_calls=3, analyst_capacity=_matrix()
    )

    record = _capacity(settings, reservations).get_capacity()

    assert record.analysts == ChannelCapacity(available=7, status="available", total=8)
    assert record.voicebot == ChannelCapacity(available=2, status="available", total=3)
    assert record.bidi.available == 7


def test_live_capacity_reads_exhausted_when_every_slot_is_taken() -> None:
    reservations = InMemoryResourceReservationRepository()
    reservations.try_acquire(
        ReservedResource.VOICEBOT, alert_id="a1", holder="a1", capacity=1, now=NOW
    )
    settings = OperationalSettings(voicebot_max_concurrent_calls=1)

    record = _capacity(settings, reservations).get_capacity()

    assert record.voicebot == ChannelCapacity(available=0, status="exhausted", total=1)


def test_live_capacity_reads_zero_unavailable_when_resources_are_switched_off() -> None:
    settings = OperationalSettings(analyst_enabled=False, voicebot_enabled=False)

    record = _capacity(settings, InMemoryResourceReservationRepository()).get_capacity()

    assert record.analysts == ChannelCapacity(
        available=0, status="unavailable", total=0
    )
    assert record.voicebot == ChannelCapacity(
        available=0, status="unavailable", total=0
    )


# --- RouteAlertResolutionUseCase -------------------------------------------


def _router(settings: OperationalSettings, reservations=None):
    reservations = reservations or InMemoryResourceReservationRepository()
    return (
        RouteAlertResolutionUseCase(
            operations_capacity=_capacity(settings, reservations),
            settings_repository=InMemoryOperationalSettingsRepository(settings),
            reservation_repository=reservations,
            clock=lambda: NOW,
        ),
        reservations,
    )


_PLAYBOOK = ModusOperandiPlaybook(
    resolution=ShortageBehavior(resolution_tag=ResolutionTag.SEND_TO_VOICEBOT),
    if_no_voicebot=ShortageBehavior(
        resolution_tag=ResolutionTag.SCALE_TO_ANALYST, resolution_method_id="rm-an"
    ),
    if_no_analyst=ShortageBehavior(
        resolution_tag=ResolutionTag.BLOCK_HARD, resolution_method_id="rm-hard"
    ),
)


def test_voicebot_decision_reserves_a_slot() -> None:
    router, reservations = _router(OperationalSettings(voicebot_max_concurrent_calls=2))

    routing = router.execute(alert_id="a1", decision="voicebot", playbook=_PLAYBOOK)

    assert routing.decision == "voicebot"
    assert routing.fallbacks == []
    held = reservations.get(routing.reservation_id)
    assert held.resource == ReservedResource.VOICEBOT and held.alert_id == "a1"


def test_voicebot_retry_reuses_the_alerts_own_slot() -> None:
    router, reservations = _router(OperationalSettings(voicebot_max_concurrent_calls=1))
    first = router.execute(alert_id="a1", decision="voicebot", playbook=_PLAYBOOK)

    again = router.execute(alert_id="a1", decision="voicebot", playbook=_PLAYBOOK)

    assert again.decision == "voicebot"
    assert again.reservation_id == first.reservation_id
    assert len(reservations.records) == 1


def test_no_voicebot_slot_follows_the_playbook_to_an_analyst() -> None:
    settings = OperationalSettings(
        voicebot_max_concurrent_calls=0, analyst_capacity=_matrix()
    )
    router, reservations = _router(settings)

    routing = router.execute(alert_id="a1", decision="voicebot", playbook=_PLAYBOOK)

    assert routing.decision == "scale_to_analyst"
    assert routing.fallbacks == [
        FallbackStep("voicebot", "voicebot_unavailable", "scale_to_analyst", "rm-an")
    ]
    # Escalating reserves nothing - the analyst reserves when taking it.
    assert reservations.records == {}


def test_no_voicebot_and_no_analyst_ends_in_the_playbooks_block() -> None:
    settings = OperationalSettings(voicebot_enabled=False, analyst_enabled=False)
    router, _ = _router(settings)

    routing = router.execute(alert_id="a1", decision="voicebot", playbook=_PLAYBOOK)

    assert routing.decision == "block"
    assert routing.block_mode == "hard"
    assert [(s.from_decision, s.to_decision) for s in routing.fallbacks] == [
        ("voicebot", "scale_to_analyst"),
        ("scale_to_analyst", "block"),
    ]


def test_without_playbook_a_short_resource_falls_back_to_block_soft() -> None:
    router, _ = _router(OperationalSettings(analyst_enabled=False))

    routing = router.execute(alert_id="a1", decision="scale_to_analyst", playbook=None)

    assert routing.decision == "block"
    assert routing.block_mode == "soft"
    assert routing.fallbacks[0].reason == "analyst_unavailable"


def test_a_fallback_chain_that_loops_back_ends_in_block_soft() -> None:
    looping = ModusOperandiPlaybook(
        if_no_voicebot=ShortageBehavior(resolution_tag=ResolutionTag.SCALE_TO_ANALYST),
        if_no_analyst=ShortageBehavior(resolution_tag=ResolutionTag.SEND_TO_VOICEBOT),
    )
    router, _ = _router(
        OperationalSettings(voicebot_enabled=False, analyst_enabled=False)
    )

    routing = router.execute(alert_id="a1", decision="voicebot", playbook=looping)

    assert routing.decision == "block"
    assert routing.block_mode == "soft"
    assert routing.fallbacks[-1].reason == "loop"


@pytest.mark.parametrize("decision", ["block", "pass", "bidi"])
def test_decisions_without_a_resource_pass_through(decision) -> None:
    router, reservations = _router(OperationalSettings(analyst_enabled=False))

    routing = router.execute(alert_id="a1", decision=decision, playbook=_PLAYBOOK)

    assert routing.decision == decision
    assert routing.fallbacks == []
    assert reservations.records == {}
