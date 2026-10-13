from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.application.ports.configuration_port import ResolutionTag, ShortageBehavior
from src.application.ports.modus_operandi_library_port import ModusOperandiPlaybook
from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.ports.operations_capacity_port import OperationsCapacityPort
from src.application.ports.resource_reservation_port import (
    ReservationConflict,
    ReservedResource,
    ResourceReservationRepository,
)

# Fallback tag -> (executor decision, block mode). handle_by_aria is never a
# valid fallback (validate_playbook rejects it); treated as a soft block if
# an old record ever carries it, the safest action that needs no LLM.
_TAG_TO_DECISION: dict[ResolutionTag, tuple[str, str | None]] = {
    ResolutionTag.SEND_TO_VOICEBOT: ("voicebot", None),
    ResolutionTag.SCALE_TO_ANALYST: ("scale_to_analyst", None),
    ResolutionTag.BLOCK_SOFT: ("block", "soft"),
    ResolutionTag.BLOCK_HARD: ("block", "hard"),
    ResolutionTag.HANDLE_BY_ARIA: ("block", "soft"),
}

_RESOURCE_DECISIONS = ("voicebot", "scale_to_analyst")


@dataclass
class FallbackStep:
    from_decision: str
    reason: str  # "voicebot_unavailable" | "analyst_unavailable" | "loop"
    to_decision: str
    resolution_method_id: str | None = None


@dataclass
class ResolutionRouting:
    """What the executor should actually do - the analyst's decision after
    checking (and, for the voicebot, reserving) the resource it needs."""

    decision: str
    # "soft" | "hard" when the final block came from a playbook fallback;
    # None for a block the analyst chose directly.
    block_mode: str | None = None
    # The voicebot slot held for this call; released by the callback.
    reservation_id: str | None = None
    fallbacks: list[FallbackStep] = field(default_factory=list)


class RouteAlertResolutionUseCase:
    """Enforces resource availability on the analyst's decision.

    The analyst LLM already saw availability, but it can change before the
    executor acts. Here:
    - voicebot: atomically reserves a slot (quota = voicebot_max_concurrent
      _calls, 0 while switched off). The slot is held until the voicebot
      callback releases it, or the reservation TTL expires.
    - scale_to_analyst: requires live analyst availability > 0. Nothing is
      reserved yet - an analyst reserves the alert when taking it from the
      queue.
    If the resource is gone, the playbook's if_no_voicebot / if_no_analyst
    applies (block_soft when there is no playbook), repeating the check for
    the fallback until a decision needs no resource. A chain that returns to
    a resource already tried ends in block_soft.
    """

    def __init__(
        self,
        operations_capacity: OperationsCapacityPort,
        settings_repository: OperationalSettingsRepository,
        reservation_repository: ResourceReservationRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._capacity = operations_capacity
        self._settings = settings_repository
        self._reservations = reservation_repository
        self._clock = clock

    def execute(
        self,
        *,
        alert_id: str,
        decision: str,
        playbook: ModusOperandiPlaybook | None,
    ) -> ResolutionRouting:
        routing = ResolutionRouting(decision=decision)
        tried: set[str] = set()
        while routing.decision in _RESOURCE_DECISIONS:
            current = routing.decision
            tried.add(current)
            if current == "voicebot":
                reservation_id = self._reserve_voicebot(alert_id)
                if reservation_id is not None:
                    routing.reservation_id = reservation_id
                    return routing
                fallback = playbook.if_no_voicebot if playbook else ShortageBehavior()
                reason = "voicebot_unavailable"
            else:
                if self._capacity.get_capacity().analysts.available > 0:
                    return routing
                fallback = playbook.if_no_analyst if playbook else ShortageBehavior()
                reason = "analyst_unavailable"
            next_decision, block_mode = _TAG_TO_DECISION[fallback.resolution_tag]
            if next_decision in tried:
                next_decision, block_mode, reason = "block", "soft", "loop"
            routing.fallbacks.append(
                FallbackStep(
                    from_decision=current,
                    reason=reason,
                    to_decision=next_decision,
                    resolution_method_id=fallback.resolution_method_id,
                )
            )
            routing.decision = next_decision
            routing.block_mode = block_mode
        return routing

    def _reserve_voicebot(self, alert_id: str) -> str | None:
        settings = self._settings.get()
        capacity = (
            settings.voicebot_max_concurrent_calls if settings.voicebot_enabled else 0
        )
        now = self._clock()
        result = self._reservations.try_acquire(
            ReservedResource.VOICEBOT,
            alert_id=alert_id,
            holder=alert_id,
            capacity=capacity,
            now=now,
        )
        if result.reservation is not None:
            return result.reservation.id
        if result.conflict == ReservationConflict.ALERT_TAKEN:
            # A Celery autoretry re-runs the executor: the slot this alert
            # reserved on the previous attempt is still its own.
            existing = next(
                (
                    r
                    for r in self._reservations.list_active(
                        ReservedResource.VOICEBOT, now
                    )
                    if r.alert_id == alert_id
                ),
                None,
            )
            return existing.id if existing is not None else None
        return None
