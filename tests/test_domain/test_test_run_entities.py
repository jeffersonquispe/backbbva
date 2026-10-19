from datetime import UTC, datetime
from uuid import uuid4

from src.domain.test_runs.entities import (
    TestRunConfig,
    TestRunRecord,
    TestRunStatus,
)


def test_test_run_config_mutable_defaults_are_independent() -> None:
    first = TestRunConfig()
    second = TestRunConfig()

    first.prompt_overrides["classification"] = "prompt"
    first.model_overrides["classification"] = "model"

    assert second.prompt_overrides == {}
    assert second.model_overrides == {}


def test_test_run_record_keeps_domain_state_and_timestamps() -> None:
    now = datetime.now(UTC)
    record = TestRunRecord(
        id=uuid4(),
        name="validation",
        dataset_name="sample",
        config=TestRunConfig(max_feedback_iterations=2),
        status=TestRunStatus.RUNNING,
        total=12,
        created_at=now,
        updated_at=now,
    )

    assert record.status is TestRunStatus.RUNNING
    assert record.finished_at is None
    assert record.config.max_feedback_iterations == 2
