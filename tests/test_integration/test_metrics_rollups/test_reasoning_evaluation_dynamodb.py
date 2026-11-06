"""Docker-only: the LLM-judge verdicts table (first writer wins, per-step
verdicts round-trip) and its per-day listing table, on a throwaway table.
Run with `make test-integration-metrics`."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip(
        "Requires DynamoDB Local (set DYNAMO_ENDPOINT)", allow_module_level=True
    )

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.manager import create_table
from src.infrastructure.persistence.database.dynamodb.repositories.alert_reasoning_evaluation_repository import (
    DynamoAlertReasoningEvaluationRepository,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERT_REASONING_EVALUATION_DAYS_TABLE,
    ALERT_REASONING_EVALUATIONS_TABLE,
)

pytestmark = pytest.mark.docker_integration

# 03:00 UTC is 22:00 of the previous day in Bogotá.
LATE_NIGHT = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)


@pytest.fixture
def repository() -> Iterator[DynamoAlertReasoningEvaluationRepository]:
    suffix = uuid.uuid4().hex[:10]
    schema = {
        **ALERT_REASONING_EVALUATIONS_TABLE,
        "TableName": f"it_reasoning_evaluations_{suffix}",
    }
    days_schema = {
        **ALERT_REASONING_EVALUATION_DAYS_TABLE,
        "TableName": f"it_reasoning_evaluation_days_{suffix}",
    }
    create_table(schema)
    create_table(days_schema)
    resource = get_dynamodb_resource()
    table = resource.Table(schema["TableName"])
    days = resource.Table(days_schema["TableName"])
    yield DynamoAlertReasoningEvaluationRepository(table, days)
    table.delete()
    days.delete()


def _record(
    *, at: datetime, hallucination: bool = False, **extra
) -> AlertReasoningEvaluationRecord:
    return AlertReasoningEvaluationRecord(
        alert_id=uuid.uuid4(),
        workflow_execution_id=uuid.uuid4(),
        status=ReasoningEvaluationStatus.EVALUATED,
        hallucination=hallucination,
        data_use_correct=not hallucination,
        rationale="Justificación en español.",
        judge_model="judge",
        evaluated_at=at,
        **extra,
    )


def test_a_verdict_round_trips_with_its_per_step_detail_and_prompt_version(
    repository,
) -> None:
    record = _record(
        at=LATE_NIGHT,
        hallucination=True,
        prompt_version="v2",
        attempts=2,
        step_verdicts={
            "classification": {
                "hallucination": True,
                "data_use_correct": False,
                "note": "Cita un monto que no existe.",
            }
        },
    )

    repository.create(record)
    stored = repository.get(record.alert_id)

    assert stored == record


def test_the_first_verdict_wins_and_a_second_create_returns_it(repository) -> None:
    first = _record(at=LATE_NIGHT, hallucination=True)
    second = AlertReasoningEvaluationRecord(
        **{**first.__dict__, "hallucination": False}
    )

    repository.create(first)

    assert repository.create(second).hallucination is True
    assert repository.get(first.alert_id).hallucination is True


def test_listing_uses_the_bogota_day_newest_first_and_respects_the_range(
    repository,
) -> None:
    night = _record(at=LATE_NIGHT)  # Bogotá: 2026-11-04 22:00
    morning = _record(at=LATE_NIGHT + timedelta(hours=10))  # Bogotá: 2026-11-05 08:00
    old = _record(at=LATE_NIGHT - timedelta(days=10))
    for record in (night, morning, old):
        repository.create(record)

    both = repository.list_between(date(2026, 11, 4), date(2026, 11, 5), limit=10)
    only_fifth = repository.list_between(date(2026, 11, 5), date(2026, 11, 5), limit=10)
    capped = repository.list_between(date(2026, 10, 1), date(2026, 11, 5), limit=2)

    assert [r.alert_id for r in both] == [morning.alert_id, night.alert_id]
    assert [r.alert_id for r in only_fifth] == [morning.alert_id]
    assert [r.alert_id for r in capped] == [morning.alert_id, night.alert_id]


def test_a_verdict_without_the_new_attributes_reads_as_a_v1_verdict(repository) -> None:
    alert_id = uuid.uuid4()
    repository._table.put_item(  # what the table held before per-step verdicts
        Item={
            "alert_id": str(alert_id),
            "workflow_execution_id": str(uuid.uuid4()),
            "status": "evaluated",
            "hallucination": False,
            "data_use_correct": True,
            "rationale": "antiguo",
            "judge_model": "judge",
            "evaluated_at": LATE_NIGHT.isoformat(),
        }
    )

    stored = repository.get(alert_id)

    assert (stored.prompt_version, stored.step_verdicts, stored.attempts) == (
        "v1",
        {},
        1,
    )


def test_a_day_entry_without_a_verdict_is_skipped_and_a_retry_on_another_day_counts_once(
    repository,
) -> None:
    orphan = _record(at=LATE_NIGHT)
    repository._days.put_item(  # the crash window: entry written, verdict never
        Item={"evaluated_day": "2026-11-04", "alert_id": str(orphan.alert_id)}
    )
    judged = _record(at=LATE_NIGHT)
    repository.create(judged)
    # A retry of the same alert that judged the next day: the verdict stays on
    # its first day, so the alert is listed once, under that day.
    later = AlertReasoningEvaluationRecord(
        **{**judged.__dict__, "evaluated_at": LATE_NIGHT + timedelta(days=1)}
    )
    assert repository.create(later).evaluated_at == judged.evaluated_at

    by_day = repository.list_between(date(2026, 11, 4), date(2026, 11, 6), limit=10)

    assert [r.alert_id for r in by_day] == [judged.alert_id]
