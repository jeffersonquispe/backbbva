from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.application.ports.fraud_history_archive_port import (
    ArchivedAlert,
    ArchiveVerificationError,
)
from src.application.use_cases.fraud_review.get_archived_alert import (
    ArchivedAlertNotFoundError,
    GetArchivedAlert,
)

NOW = datetime(2026, 11, 4, tzinfo=UTC)
ARCHIVED = ArchivedAlert("a1", date(2025, 10, 26), "key", {"alert_id": "a1"})


class InMemoryClock:
    def now(self) -> datetime:
        return NOW


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list = []

    def write(self, entry) -> None:
        self.entries.append(entry)


class InMemoryArchiveReader:
    def __init__(self, found: bool = True, corrupt: bool = False) -> None:
        self.found, self.corrupt = found, corrupt

    def get_archived_alert(self, alert_id: str):
        if self.corrupt:
            raise ArchiveVerificationError(alert_id)
        return ARCHIVED if self.found else None


def _summary(audit: RecordingAudit):
    return [
        (e.action, e.actor_id, e.entity_type, e.entity_id, e.outcome)
        for e in audit.entries
    ]


def test_a_read_is_audited_with_who_asked_for_which_alert() -> None:
    audit = RecordingAudit()

    out = GetArchivedAlert(InMemoryArchiveReader(), audit, InMemoryClock()).execute(
        "a1", requested_by="u1"
    )

    assert out.archived == ARCHIVED
    assert _summary(audit) == [
        ("fraud_history.archive.read", "u1", "archived_alert", "a1", "success")
    ]
    assert audit.entries[0].occurred_at == NOW


def test_unknown_and_corrupt_reads_are_audited_too() -> None:
    audit = RecordingAudit()

    with pytest.raises(ArchivedAlertNotFoundError):
        GetArchivedAlert(
            InMemoryArchiveReader(found=False), audit, InMemoryClock()
        ).execute("a1", requested_by="u1")
    with pytest.raises(ArchiveVerificationError):
        GetArchivedAlert(
            InMemoryArchiveReader(corrupt=True), audit, InMemoryClock()
        ).execute("a1", requested_by="u2")

    assert [(e.actor_id, e.outcome) for e in audit.entries] == [
        ("u1", "not_found"),
        ("u2", "failure"),
    ]
