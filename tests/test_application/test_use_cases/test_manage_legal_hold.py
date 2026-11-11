from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from src.application.ports.legal_hold_port import LegalHold
from src.application.use_cases.fraud_review.manage_legal_hold import (
    LegalHoldAlertNotFoundError,
    LegalHoldAlreadyActiveError,
    LegalHoldNotActiveError,
    LegalHoldReasonError,
    ListLegalHolds,
    PlaceLegalHold,
    ReleaseLegalHold,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
HOT = uuid4()
ARCHIVED = "archived-alert-1"
REASON = "Requerimiento judicial 123 sobre el cliente"


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list = []

    def write(self, entry) -> None:
        self.entries.append(entry)


class InMemoryClock:
    def now(self) -> datetime:
        return NOW


class InMemoryAlerts:
    def get(self, alert_id: UUID):
        return object() if alert_id == HOT else None


class InMemoryArchive:
    def is_archived(self, alert_id: str) -> bool:
        return alert_id == ARCHIVED


class InMemoryLegalHolds:
    def __init__(self) -> None:
        self.rows: dict[str, LegalHold] = {}

    def place(self, hold: LegalHold) -> bool:
        current = self.rows.get(hold.alert_id)
        if current is not None and current.active:
            return False
        self.rows[hold.alert_id] = hold
        return True

    def release(self, alert_id, *, released_by, release_reason, released_at):
        current = self.rows.get(alert_id)
        if current is None or not current.active:
            return None
        released = LegalHold(
            current.alert_id,
            current.reason,
            current.case_reference,
            current.placed_by,
            current.placed_at,
            released_at,
            released_by,
            release_reason,
        )
        self.rows[alert_id] = released
        return released

    def get(self, alert_id: str):
        return self.rows.get(alert_id)

    def list_active(self, limit: int = 100) -> list[LegalHold]:
        return [h for h in self.rows.values() if h.active][:limit]

    def active_ids(self, alert_ids: Sequence[str]) -> set[str]:
        return {a for a in alert_ids if a in self.rows and self.rows[a].active}


def _place(
    holds: InMemoryLegalHolds, audit: RecordingAudit | None = None
) -> PlaceLegalHold:
    return PlaceLegalHold(
        holds,
        InMemoryAlerts(),
        InMemoryArchive(),
        InMemoryClock(),
        audit or RecordingAudit(),
    )


def test_a_hot_alert_can_be_held_with_who_when_why_and_the_case() -> None:
    holds = InMemoryLegalHolds()

    hold = _place(holds).execute(
        alert_id=str(HOT),
        reason=f"  {REASON}  ",
        case_reference=" CASO-9 ",
        placed_by="u1",
    )

    assert holds.get(str(HOT)) == hold
    assert (hold.reason, hold.case_reference, hold.placed_by, hold.placed_at) == (
        REASON,
        "CASO-9",
        "u1",
        NOW,
    )
    assert hold.active


def test_an_already_archived_alert_can_be_held_too() -> None:
    holds = InMemoryLegalHolds()

    _place(holds).execute(
        alert_id=ARCHIVED, reason=REASON, case_reference=None, placed_by="u1"
    )

    assert holds.active_ids([ARCHIVED]) == {ARCHIVED}


def test_an_alert_that_exists_nowhere_cannot_be_held() -> None:
    for alert_id in (str(uuid4()), "not-a-uuid-and-not-archived"):
        with pytest.raises(LegalHoldAlertNotFoundError):
            _place(InMemoryLegalHolds()).execute(
                alert_id=alert_id, reason=REASON, case_reference=None, placed_by="u1"
            )


@pytest.mark.parametrize("reason", ["", "   ", "corto", "x" * 1_001])
def test_the_reason_is_mandatory_and_bounded(reason: str) -> None:
    holds = InMemoryLegalHolds()

    with pytest.raises(LegalHoldReasonError):
        _place(holds).execute(
            alert_id=str(HOT), reason=reason, case_reference=None, placed_by="u1"
        )
    assert holds.rows == {}


def test_a_second_hold_on_the_same_alert_is_refused_until_it_is_released() -> None:
    holds = InMemoryLegalHolds()
    place = _place(holds)
    place.execute(alert_id=str(HOT), reason=REASON, case_reference=None, placed_by="u1")

    with pytest.raises(LegalHoldAlreadyActiveError):
        place.execute(
            alert_id=str(HOT), reason=REASON, case_reference=None, placed_by="u2"
        )

    ReleaseLegalHold(holds, InMemoryClock(), RecordingAudit()).execute(
        alert_id=str(HOT), reason="El caso se cerró sin hallazgos", released_by="u1"
    )
    again = place.execute(
        alert_id=str(HOT), reason=REASON, case_reference="CASO-10", placed_by="u2"
    )
    assert again.active and again.placed_by == "u2"


def test_release_records_who_when_and_why_and_needs_an_active_hold() -> None:
    holds = InMemoryLegalHolds()
    _place(holds).execute(
        alert_id=str(HOT), reason=REASON, case_reference=None, placed_by="u1"
    )
    release = ReleaseLegalHold(holds, InMemoryClock(), RecordingAudit())

    released = release.execute(
        alert_id=str(HOT), reason="Oficio de levantamiento 77", released_by="u3"
    )

    assert not released.active
    assert (released.released_by, released.released_at, released.release_reason) == (
        "u3",
        NOW,
        "Oficio de levantamiento 77",
    )
    with pytest.raises(LegalHoldNotActiveError):
        release.execute(
            alert_id=str(HOT), reason="Segundo intento largo", released_by="u3"
        )
    with pytest.raises(LegalHoldReasonError):
        release.execute(alert_id=str(HOT), reason="no", released_by="u3")


def test_listing_shows_only_active_holds() -> None:
    holds = InMemoryLegalHolds()
    place = _place(holds)
    place.execute(alert_id=str(HOT), reason=REASON, case_reference=None, placed_by="u1")
    place.execute(alert_id=ARCHIVED, reason=REASON, case_reference=None, placed_by="u1")
    ReleaseLegalHold(holds, InMemoryClock(), RecordingAudit()).execute(
        alert_id=str(HOT), reason="Levantado por oficio 5", released_by="u1"
    )

    assert [h.alert_id for h in ListLegalHolds(holds).execute()] == [ARCHIVED]


def test_placing_and_releasing_are_audited_with_the_actor_and_the_alert() -> None:
    holds, audit = InMemoryLegalHolds(), RecordingAudit()
    _place(holds, audit).execute(
        alert_id=str(HOT), reason=REASON, case_reference=None, placed_by="u1"
    )
    ReleaseLegalHold(holds, InMemoryClock(), audit).execute(
        alert_id=str(HOT), reason="Levantado por oficio 5", released_by="u2"
    )
    with pytest.raises(LegalHoldNotActiveError):
        ReleaseLegalHold(holds, InMemoryClock(), audit).execute(
            alert_id=str(HOT), reason="Levantado por oficio 5", released_by="u2"
        )

    assert [(e.action, e.actor_id, e.entity_id, e.outcome) for e in audit.entries] == [
        ("legal_hold.place", "u1", str(HOT), "success"),
        ("legal_hold.release", "u2", str(HOT), "success"),
    ]
