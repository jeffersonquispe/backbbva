"""Find archived alerts by ``alert_id``, ``event_id`` or creation day.

Answers from the archive index alone (no object is read), flags the alerts
under legal hold, and writes an audit entry with who searched for what."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import uuid4

from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.fraud_history_archive_port import ArchivedAlertSummary
from src.application.ports.fraud_history_archive_reader_port import (
    FraudHistoryArchiveReaderPort,
)
from src.application.ports.legal_hold_port import LegalHoldRepository

MAX_RESULTS = 200


class ArchiveSearchCriteriaError(ValueError):
    """Exactly one of alert_id, event_id or day is required."""


@dataclass(frozen=True)
class ArchivedAlertHit:
    summary: ArchivedAlertSummary
    legal_hold: bool


class SearchArchivedAlerts:
    def __init__(
        self,
        reader: FraudHistoryArchiveReaderPort,
        holds: LegalHoldRepository,
        audit: AuditPort,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._holds = holds
        self._audit = audit
        self._clock = clock

    def execute(
        self,
        *,
        requested_by: str,
        alert_id: str | None = None,
        event_id: str | None = None,
        day: date | None = None,
        limit: int = 100,
    ) -> list[ArchivedAlertHit]:
        alert_id, event_id = (
            (alert_id or "").strip() or None,
            (event_id or "").strip() or None,
        )
        if sum(value is not None for value in (alert_id, event_id, day)) != 1:
            raise ArchiveSearchCriteriaError(
                "use exactly one of alert_id, event_id or day"
            )
        summaries = self._reader.search(
            alert_id=alert_id,
            event_id=event_id,
            created_day=day,
            limit=max(1, min(limit, MAX_RESULTS)),
        )
        held = self._holds.active_ids([s.alert_id for s in summaries])
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=requested_by,
                worker_name=None,
                action="fraud_history.archive.search",
                entity_type="archived_alert",
                entity_id=alert_id or event_id or (day.isoformat() if day else None),
                correlation_id=str(uuid4()),
                parent_id=None,
                occurred_at=self._clock.now(),
                outcome="success" if summaries else "not_found",
            )
        )
        return [ArchivedAlertHit(s, s.alert_id in held) for s in summaries]
