"""Place, release and list legal holds on alerts (#11c).

A hold keeps a live alert out of the fraud-history archive, and keeps the
archived day object holding an already-archived alert from being deleted by a
retention sweep. Both need a reason; the case reference is optional. Who placed
or released it, when and why stays on the row, and every write also goes
through the audited DynamoDB client.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from src.application.ports.alert_port import AlertRepository
from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.fraud_history_archive_reader_port import (
    FraudHistoryArchiveReaderPort,
)
from src.application.ports.legal_hold_port import LegalHold, LegalHoldRepository

MIN_REASON_CHARS = 10
MAX_REASON_CHARS = 1_000
MAX_CASE_REFERENCE_CHARS = 100


class LegalHoldAlertNotFoundError(Exception):
    """The alert is neither hot nor archived, so there is nothing to hold."""


class LegalHoldAlreadyActiveError(Exception):
    pass


class LegalHoldNotActiveError(Exception):
    pass


class LegalHoldReasonError(ValueError):
    pass


def _audit(
    audit: AuditPort, clock: Clock, action: str, alert_id: str, actor_id: str
) -> None:
    audit.write(
        AuditEntry(
            actor_type="user",
            actor_id=actor_id,
            worker_name=None,
            action=action,
            entity_type="legal_hold",
            entity_id=alert_id,
            correlation_id=str(uuid4()),
            parent_id=None,
            occurred_at=clock.now(),
            outcome="success",
        )
    )


def _clean_reason(reason: str) -> str:
    text = reason.strip()
    if not MIN_REASON_CHARS <= len(text) <= MAX_REASON_CHARS:
        raise LegalHoldReasonError(
            f"reason must have {MIN_REASON_CHARS}-{MAX_REASON_CHARS} characters"
        )
    return text


class PlaceLegalHold:
    def __init__(
        self,
        holds: LegalHoldRepository,
        alerts: AlertRepository,
        archive: FraudHistoryArchiveReaderPort,
        clock: Clock,
        audit: AuditPort,
    ) -> None:
        self._holds = holds
        self._alerts = alerts
        self._archive = archive
        self._clock = clock
        self._audit = audit

    def execute(
        self,
        *,
        alert_id: str,
        reason: str,
        case_reference: str | None,
        placed_by: str,
    ) -> LegalHold:
        text = _clean_reason(reason)
        reference = (case_reference or "").strip() or None
        if reference and len(reference) > MAX_CASE_REFERENCE_CHARS:
            raise LegalHoldReasonError(
                f"case_reference must have at most {MAX_CASE_REFERENCE_CHARS} characters"
            )
        if not self._exists(alert_id):
            raise LegalHoldAlertNotFoundError(alert_id)
        hold = LegalHold(
            alert_id=alert_id,
            reason=text,
            case_reference=reference,
            placed_by=placed_by,
            placed_at=self._clock.now(),
        )
        if not self._holds.place(hold):
            raise LegalHoldAlreadyActiveError(alert_id)
        _audit(self._audit, self._clock, "legal_hold.place", alert_id, placed_by)
        return hold

    def _exists(self, alert_id: str) -> bool:
        try:
            parsed: UUID | None = UUID(alert_id)
        except ValueError:
            parsed = None  # not a live alert id; it may still be an archived one
        if parsed is not None and self._alerts.get(parsed) is not None:
            return True
        return self._archive.is_archived(alert_id)


class ReleaseLegalHold:
    def __init__(
        self, holds: LegalHoldRepository, clock: Clock, audit: AuditPort
    ) -> None:
        self._holds = holds
        self._clock = clock
        self._audit = audit

    def execute(self, *, alert_id: str, reason: str, released_by: str) -> LegalHold:
        released = self._holds.release(
            alert_id,
            released_by=released_by,
            release_reason=_clean_reason(reason),
            released_at=self._clock.now(),
        )
        if released is None:
            raise LegalHoldNotActiveError(alert_id)
        _audit(self._audit, self._clock, "legal_hold.release", alert_id, released_by)
        return released


class ListLegalHolds:
    def __init__(self, holds: LegalHoldRepository) -> None:
        self._holds = holds

    def execute(self, limit: int = 100) -> list[LegalHold]:
        return self._holds.list_active(limit=limit)


class LegalHoldNotFoundError(Exception):
    pass


class GetLegalHold:
    def __init__(self, holds: LegalHoldRepository) -> None:
        self._holds = holds

    def execute(self, alert_id: str) -> LegalHold:
        hold = self._holds.get(alert_id)
        if hold is None:
            raise LegalHoldNotFoundError(alert_id)
        return hold
