from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from src.application.ports.fraud_history_archive_port import ArchivedAlertSummary
from src.application.use_cases.fraud_review.search_archived_alerts import (
    ArchiveSearchCriteriaError,
    SearchArchivedAlerts,
)

DAY = date(2025, 10, 26)
NOW = datetime(2026, 11, 4, tzinfo=UTC)
ROWS = [
    ArchivedAlertSummary("a1", "EV-1", DAY),
    ArchivedAlertSummary("a2", "EV-2", DAY),
]


class InMemoryClock:
    def now(self) -> datetime:
        return NOW


class RecordingAudit:
    def __init__(self) -> None:
        self.entries: list = []

    def write(self, entry) -> None:
        self.entries.append(entry)


class RecordingReader:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["alert_id"]:
            return [r for r in ROWS if r.alert_id == kwargs["alert_id"]]
        if kwargs["event_id"]:
            return [r for r in ROWS if r.event_id == kwargs["event_id"]]
        return ROWS


class InMemoryLegalHolds:
    def active_ids(self, alert_ids):
        return {a for a in alert_ids if a == "a2"}


def _use_case(audit: RecordingAudit, reader: RecordingReader | None = None):
    return SearchArchivedAlerts(
        reader or RecordingReader(), InMemoryLegalHolds(), audit, InMemoryClock()
    )


def test_exactly_one_criterion_is_required() -> None:
    use_case = _use_case(RecordingAudit())
    for kwargs in ({}, {"alert_id": "a1", "event_id": "EV-1"}, {"alert_id": "  "}):
        with pytest.raises(ArchiveSearchCriteriaError):
            use_case.execute(requested_by="u1", **kwargs)


def test_hits_are_flagged_with_the_alerts_under_legal_hold() -> None:
    hits = _use_case(RecordingAudit()).execute(requested_by="u1", day=DAY)

    assert [(h.summary.alert_id, h.legal_hold) for h in hits] == [("a1", False), ("a2", True)]


def test_search_is_audited_with_who_and_what_even_without_results() -> None:
    audit = RecordingAudit()
    use_case = _use_case(audit)

    use_case.execute(requested_by="u1", event_id=" EV-1 ")
    use_case.execute(requested_by="u2", event_id="EV-none")
    use_case.execute(requested_by="u3", day=DAY)

    assert [(e.action, e.actor_id, e.entity_id, e.outcome) for e in audit.entries] == [
        ("fraud_history.archive.search", "u1", "EV-1", "success"),
        ("fraud_history.archive.search", "u2", "EV-none", "not_found"),
        ("fraud_history.archive.search", "u3", "2025-10-26", "success"),
    ]


def test_the_limit_is_bounded() -> None:
    reader = RecordingReader()

    _use_case(RecordingAudit(), reader).execute(requested_by="u1", day=DAY, limit=10_000)
    _use_case(RecordingAudit(), reader).execute(requested_by="u1", day=DAY, limit=0)

    assert [c["limit"] for c in reader.calls] == [200, 1]
