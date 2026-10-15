from datetime import UTC, datetime, timedelta

import pytest

from src.application.ports.clock_port import Clock
from src.application.ports.object_storage_port import ObjectInfo, ObjectStoragePort
from src.application.use_cases.object_storage.apply_retention import (
    ApplyObjectStorageRetentionUseCase,
    RetentionRule,
)

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class InMemoryObjectStoragePort(ObjectStoragePort):
    def __init__(self, ages_days: dict[str, int], failing: set[str] | None = None):
        self.objects = {
            key: ObjectInfo(key, 10, NOW - timedelta(days=age))
            for key, age in ages_days.items()
        }
        self.failing = failing or set()
        self.deleted: list[str] = []

    def list_objects(self, prefix: str = "") -> list[ObjectInfo]:
        return [o for k, o in self.objects.items() if k.startswith(prefix)]

    def delete(self, key: str) -> None:
        if key in self.failing:
            raise RuntimeError("boom")
        self.deleted.append(key)
        del self.objects[key]


def _use_case(reports: InMemoryObjectStoragePort):
    return ApplyObjectStorageRetentionUseCase({"reports": reports}, FixedClock())


def test_deletes_only_expired_objects_under_prefix():
    reports = InMemoryObjectStoragePort(
        {"alerts/a/old.json": 100, "alerts/a/new.json": 5, "other/old.json": 100}
    )
    out = _use_case(reports).execute(
        [RetentionRule("reports", "alerts/", 30)], dry_run=False
    )
    assert reports.deleted == ["alerts/a/old.json"]
    assert out.deleted == 1
    assert out.results[0].matched == 1
    assert out.results[0].bytes_matched == 10


def test_dry_run_reports_matches_without_deleting():
    reports = InMemoryObjectStoragePort({"alerts/a/old.json": 100})
    out = _use_case(reports).execute([RetentionRule("reports", "alerts/", 30)])
    assert reports.deleted == []
    assert out.dry_run is True
    assert out.results[0].matched == 1
    assert out.results[0].deleted == 0


def test_failed_delete_does_not_stop_the_sweep():
    reports = InMemoryObjectStoragePort(
        {"alerts/a": 100, "alerts/b": 100}, failing={"alerts/a"}
    )
    out = _use_case(reports).execute(
        [RetentionRule("reports", "alerts/", 30)], dry_run=False
    )
    assert reports.deleted == ["alerts/b"]
    assert out.results[0].failed == 1


def test_unknown_store_is_rejected():
    with pytest.raises(ValueError):
        _use_case(InMemoryObjectStoragePort({})).execute(
            [RetentionRule("nope", "x/", 1)]
        )


def test_rule_rejects_empty_prefix_and_zero_age():
    with pytest.raises(ValueError):
        RetentionRule("reports", " ", 30)
    with pytest.raises(ValueError):
        RetentionRule("reports", "alerts/", 0)
