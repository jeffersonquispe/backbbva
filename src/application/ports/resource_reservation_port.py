from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

# Safety TTL for both resources: a voicebot slot whose callback never
# arrives, or an analyst who takes an alert and never resolves it, frees
# the resource after this long instead of leaking it forever.
RESERVATION_TTL = timedelta(minutes=30)


class ReservedResource(StrEnum):
    VOICEBOT = "voicebot"
    ANALYST = "analyst"


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    # Never written eagerly: an ACTIVE reservation past expires_at is
    # already free (its locks no longer block anyone). The repository marks
    # it EXPIRED when it notices - on read, or when the freed slot is
    # claimed by someone else.
    EXPIRED = "EXPIRED"


@dataclass
class ResourceReservation:
    id: str
    resource: ReservedResource
    alert_id: str
    # Who holds it: the analyst's user id, or the alert id itself for a
    # voicebot call (a call has no human holder).
    holder: str
    slot: int
    reserved_at: datetime
    expires_at: datetime
    status: ReservationStatus = ReservationStatus.ACTIVE
    released_at: datetime | None = None
    release_reason: str | None = None
    # Free-form data attached on release - e.g. the voicebot callback's
    # outcome, or the analyst's resolution.
    detail: dict[str, Any] = field(default_factory=dict)

    def is_active(self, now: datetime) -> bool:
        return self.status == ReservationStatus.ACTIVE and self.expires_at > now


class ReservationConflict(StrEnum):
    """Why try_acquire returned no reservation."""

    NO_CAPACITY = "no_capacity"
    ALERT_TAKEN = "alert_taken"
    HOLDER_BUSY = "holder_busy"


@dataclass(frozen=True)
class AcquireResult:
    reservation: ResourceReservation | None
    conflict: ReservationConflict | None = None


class ResourceReservationRepository(Protocol):
    """Fixed-quota slots with expiry. try_acquire is atomic: it claims one
    free slot in [0, capacity), plus a per-alert lock (one holder per alert
    per resource) and a per-holder lock (one alert per holder) - so neither
    concurrent workers nor two analysts can over-book."""

    def try_acquire(
        self,
        resource: ReservedResource,
        *,
        alert_id: str,
        holder: str,
        capacity: int,
        now: datetime,
        ttl: timedelta = RESERVATION_TTL,
    ) -> AcquireResult: ...

    def release(
        self,
        reservation_id: str,
        *,
        reason: str,
        now: datetime,
        detail: dict[str, Any] | None = None,
    ) -> ResourceReservation | None:
        """Frees the slot/locks and records why. Returns None if the id is
        unknown; returns the record unchanged if it was no longer ACTIVE."""
        ...

    def get(self, reservation_id: str) -> ResourceReservation | None: ...

    def list_active(
        self, resource: ReservedResource, now: datetime
    ) -> list[ResourceReservation]: ...
