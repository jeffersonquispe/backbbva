from __future__ import annotations

from datetime import date

import pytest

from src.application.ports.fraud_history_archive_port import FraudHistoryDayArchive
from src.application.use_cases.fraud_review.archive_fraud_history import (
    ArchiveFraudHistoryOutput,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.worker.celery import tasks


class RecordingArchiveFraudHistory:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def execute(self, *, hot_days, scan_days, dry_run=True) -> ArchiveFraudHistoryOutput:
        self.calls.append(
            {"hot_days": hot_days, "scan_days": scan_days, "dry_run": dry_run}
        )
        return ArchiveFraudHistoryOutput(
            dry_run=dry_run,
            days=[
                FraudHistoryDayArchive(date(2025, 10, 25), 0, 0, 0, 0, None, None),
                FraudHistoryDayArchive(
                    date(2025, 10, 26),
                    2,
                    1,
                    1,
                    0 if dry_run else 2,
                    "fraud-history-archive/created_day=2025-10-26/abc.jsonl.gz",
                    "abc",
                ),
            ],
        )


def test_task_is_a_noop_when_retention_is_disabled(monkeypatch) -> None:
    use_case = RecordingArchiveFraudHistory()
    monkeypatch.setattr(genai_config, "FRAUD_HISTORY_RETENTION_ENABLED", False)
    monkeypatch.setattr(tasks, "get_archive_fraud_history_use_case", lambda: use_case)

    assert tasks.archive_fraud_history() == {"enabled": False}
    assert use_case.calls == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_task_passes_config_and_reports_only_days_with_alerts(
    monkeypatch, dry_run
) -> None:
    use_case = RecordingArchiveFraudHistory()
    monkeypatch.setattr(genai_config, "FRAUD_HISTORY_RETENTION_ENABLED", True)
    monkeypatch.setattr(genai_config, "FRAUD_HISTORY_RETENTION_DRY_RUN", dry_run)
    monkeypatch.setattr(genai_config, "FRAUD_HISTORY_HOT_DAYS", 400)
    monkeypatch.setattr(genai_config, "FRAUD_HISTORY_RETENTION_SCAN_DAYS", 2)
    monkeypatch.setattr(tasks, "get_archive_fraud_history_use_case", lambda: use_case)

    result = tasks.archive_fraud_history()

    assert use_case.calls == [{"hot_days": 400, "scan_days": 2, "dry_run": dry_run}]
    assert result["enabled"] is True and result["dry_run"] is dry_run
    assert result["alerts"] == 2 and result["deleted"] == (0 if dry_run else 2)
    assert result["days"] == [
        {
            "created_day": "2025-10-26",
            "alerts": 2,
            "reviews": 1,
            "held": 1,
            "deleted": 0 if dry_run else 2,
            "object_key": "fraud-history-archive/created_day=2025-10-26/abc.jsonl.gz",
            "sha256": "abc",
        }
    ]


def test_task_is_registered_under_its_beat_name() -> None:
    assert tasks.archive_fraud_history.name == "fraud_history.retention"
