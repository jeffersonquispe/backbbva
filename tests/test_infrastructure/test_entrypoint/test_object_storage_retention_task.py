from __future__ import annotations

import json

import pytest

from src.application.use_cases.object_storage.apply_retention import (
    ApplyRetentionOutput,
    RetentionRule,
    RetentionRuleResult,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.worker.celery import tasks
from src.infrastructure.workflows.celery import task_factories


class RecordingRetentionUseCase:
    def __init__(self) -> None:
        self.calls: list[tuple[list[RetentionRule], bool]] = []

    def execute(self, rules, dry_run=True) -> ApplyRetentionOutput:
        self.calls.append((list(rules), dry_run))
        return ApplyRetentionOutput(
            dry_run=dry_run,
            results=[
                RetentionRuleResult(
                    rule=rules[0],
                    matched=4,
                    deleted=0 if dry_run else 4,
                    bytes_matched=40,
                )
            ],
        )


def _set_rules(monkeypatch, rules) -> None:
    monkeypatch.setattr(
        genai_config, "OBJECT_STORAGE_RETENTION_RULES", json.dumps(rules)
    )


def test_rules_are_parsed_from_json_config(monkeypatch) -> None:
    _set_rules(
        monkeypatch,
        [{"store": "reports", "prefix": "alerts/", "max_age_days": "30"}],
    )

    assert task_factories.get_object_storage_retention_rules() == [
        RetentionRule("reports", "alerts/", 30)
    ]


def test_empty_rules_config_yields_no_rules(monkeypatch) -> None:
    monkeypatch.setattr(genai_config, "OBJECT_STORAGE_RETENTION_RULES", "")

    assert task_factories.get_object_storage_retention_rules() == []


@pytest.mark.parametrize(
    "rule",
    [
        {"store": "reports", "prefix": "", "max_age_days": 30},
        {"store": "reports", "prefix": "alerts/", "max_age_days": 0},
    ],
)
def test_dangerous_rules_are_rejected_at_load(monkeypatch, rule) -> None:
    _set_rules(monkeypatch, [rule])

    with pytest.raises(ValueError):
        task_factories.get_object_storage_retention_rules()


def test_task_is_a_noop_when_retention_is_disabled(monkeypatch) -> None:
    use_case = RecordingRetentionUseCase()
    monkeypatch.setattr(genai_config, "OBJECT_STORAGE_RETENTION_ENABLED", False)
    monkeypatch.setattr(
        tasks, "get_apply_object_storage_retention_use_case", lambda: use_case
    )

    assert tasks.apply_object_storage_retention() == {"enabled": False}
    assert use_case.calls == []


@pytest.mark.parametrize("dry_run", [True, False])
def test_task_passes_dry_run_flag_and_reports_per_rule(monkeypatch, dry_run) -> None:
    use_case = RecordingRetentionUseCase()
    rule = RetentionRule("reports", "alerts/", 30)
    monkeypatch.setattr(genai_config, "OBJECT_STORAGE_RETENTION_ENABLED", True)
    monkeypatch.setattr(genai_config, "OBJECT_STORAGE_RETENTION_DRY_RUN", dry_run)
    monkeypatch.setattr(
        tasks, "get_apply_object_storage_retention_use_case", lambda: use_case
    )
    monkeypatch.setattr(tasks, "get_object_storage_retention_rules", lambda: [rule])

    result = tasks.apply_object_storage_retention()

    assert use_case.calls == [([rule], dry_run)]
    assert result["enabled"] is True and result["dry_run"] is dry_run
    assert result["deleted"] == (0 if dry_run else 4)
    assert result["rules"] == [
        {
            "store": "reports",
            "prefix": "alerts/",
            "max_age_days": 30,
            "matched": 4,
            "deleted": 0 if dry_run else 4,
            "failed": 0,
            "bytes_matched": 40,
        }
    ]


def test_task_is_registered_under_its_beat_name() -> None:
    assert tasks.apply_object_storage_retention.name == "object_storage.retention"
