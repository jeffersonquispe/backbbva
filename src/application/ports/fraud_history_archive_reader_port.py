from __future__ import annotations

from abc import ABC
from datetime import date

from src.application.ports.fraud_history_archive_port import (
    ArchivedAlert,
    ArchivedAlertSummary,
    ArchiveIndexBackfillResult,
)


class FraudHistoryArchiveReaderPort(ABC):
    def get_archived_alert(self, alert_id: str) -> ArchivedAlert | None:
        """The alert (with its fraud-label reviews) from cold storage, or
        ``None`` when it was never archived. Raises if the content does not
        match its recorded SHA-256."""
        raise NotImplementedError

    def search(
        self,
        *,
        alert_id: str | None = None,
        event_id: str | None = None,
        created_day: date | None = None,
        limit: int = 100,
    ) -> list[ArchivedAlertSummary]:
        """Archived alerts matching exactly one criterion, from the index only."""
        raise NotImplementedError

    def is_archived(self, alert_id: str) -> bool:
        raise NotImplementedError

    def backfill_index(self, *, dry_run: bool) -> ArchiveIndexBackfillResult:
        """Index every alert of the archive objects written before the index
        existed (or after an index loss). Idempotent."""
        raise NotImplementedError
