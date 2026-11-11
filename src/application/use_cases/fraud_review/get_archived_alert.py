"""Read one alert back from the cold fraud-history archive by ``alert_id``.

Reading cold data is audited here, with who asked for which ``alert_id``: the
HTTP audit only records the route template, not the id in the path."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.application.ports.audit_port import AuditEntry, AuditPort
from src.application.ports.clock_port import Clock
from src.application.ports.fraud_history_archive_port import (
    ArchivedAlert,
    ArchiveVerificationError,
)
from src.application.ports.fraud_history_archive_reader_port import (
    FraudHistoryArchiveReaderPort,
)


class ArchivedAlertNotFoundError(Exception):
    """The alert was never archived (it may still be hot, or not exist)."""


@dataclass(frozen=True)
class GetArchivedAlertOutput:
    archived: ArchivedAlert


class GetArchivedAlert:
    def __init__(
        self,
        reader: FraudHistoryArchiveReaderPort,
        audit: AuditPort,
        clock: Clock,
    ) -> None:
        self._reader = reader
        self._audit = audit
        self._clock = clock

    def execute(self, alert_id: str, *, requested_by: str) -> GetArchivedAlertOutput:
        try:
            archived = self._reader.get_archived_alert(alert_id)
        except ArchiveVerificationError:
            self._record(alert_id, requested_by, "failure")
            raise
        if archived is None:
            self._record(alert_id, requested_by, "not_found")
            raise ArchivedAlertNotFoundError(alert_id)
        self._record(alert_id, requested_by, "success")
        return GetArchivedAlertOutput(archived)

    def _record(self, alert_id: str, requested_by: str, outcome: str) -> None:
        self._audit.write(
            AuditEntry(
                actor_type="user",
                actor_id=requested_by,
                worker_name=None,
                action="fraud_history.archive.read",
                entity_type="archived_alert",
                entity_id=alert_id,
                correlation_id=str(uuid4()),
                parent_id=None,
                occurred_at=self._clock.now(),
                outcome=outcome,
            )
        )
