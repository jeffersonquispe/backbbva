"""R8 / D6 - Docker-only integration tests against DynamoDB Local:
apply_once (marker Put + ADDs in one TransactWriteItems; a known marker
cancels the whole transaction) and the first-writer-wins evaluation table.
Run with `make test-integration-metrics`."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest

if not os.getenv("DYNAMO_ENDPOINT"):
    pytest.skip(
        "Requires DynamoDB Local (set DYNAMO_ENDPOINT)", allow_module_level=True
    )

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.application.ports.metrics_rollup_port import (
    TECHNICAL_ALERT_DIMENSIONS,
    MetricsDataType,
    RollupApplyMarker,
    RollupLevel,
)
from src.application.use_cases.metrics.technical_rollup_contribution import (
    TechnicalContribution,
    technical_deltas,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.manager import create_table
from src.infrastructure.persistence.database.dynamodb.repositories.alert_reasoning_evaluation_repository import (
    DynamoAlertReasoningEvaluationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.metrics_rollup_repository import (
    MARKER_SORT_KEY,
    DynamoMetricsRollupRepository,
    marker_partition_key,
    partition_key,
    sort_key,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    ALERT_REASONING_EVALUATIONS_TABLE,
    METRICS_ROLLUPS_TABLE,
)

pytestmark = pytest.mark.docker_integration

TZ = "America/Bogota"


@pytest.fixture(scope="module")
def rollups() -> DynamoMetricsRollupRepository:
    create_table(METRICS_ROLLUPS_TABLE)
    create_table(ALERT_REASONING_EVALUATIONS_TABLE)
    return DynamoMetricsRollupRepository(TZ)


def test_apply_once_counts_a_step_once(rollups) -> None:
    tag = f"itest-{uuid.uuid4()}"
    dims = tuple(
        (name, tag if name == "segment" else "unknown")
        for name in TECHNICAL_ALERT_DIMENSIONS
    ) + (("step_name", "classification"), ("model", "gpt-a"))
    now = datetime.now(UTC)
    deltas = technical_deltas(
        [
            TechnicalContribution(
                MetricsDataType.LLM_CALL, dims, {"count": 1, "input_tokens": 120}
            )
        ],
        now,
        now,
        TZ,
    )
    marker = RollupApplyMarker(scope="workflow_step", key=str(uuid.uuid4()))
    table = get_dynamodb_resource().Table(METRICS_ROLLUPS_TABLE["TableName"])
    try:
        assert rollups.apply_once(deltas, marker) is True
        assert rollups.apply_once(deltas, marker) is False  # retry: nothing written
        for delta in deltas:
            rows = rollups.query(
                MetricsDataType.LLM_CALL,
                delta.key.level,
                [delta.key.period],
                {"segment": [tag]},
            )
            assert [row.total("input_tokens") for row in rows] == [120]
        stored = table.get_item(
            Key={"pk": marker_partition_key(marker), "sk": MARKER_SORT_KEY}
        )["Item"]
        assert int(stored["expires_at"]) > now.timestamp()
        levels = {d.key.level for d in deltas}
        assert levels == {RollupLevel.DAY, RollupLevel.MONTH, RollupLevel.YEAR}
    finally:
        table.delete_item(
            Key={"pk": marker_partition_key(marker), "sk": MARKER_SORT_KEY}
        )
        for delta in deltas:
            table.delete_item(
                Key={
                    "pk": partition_key(
                        delta.key.data_type, delta.key.level, delta.key.period
                    ),
                    "sk": sort_key(delta.key.dimensions),
                }
            )


def test_evaluation_first_writer_wins(rollups) -> None:
    repository = DynamoAlertReasoningEvaluationRepository()
    alert_id = uuid.uuid4()
    first = AlertReasoningEvaluationRecord(
        alert_id=alert_id,
        workflow_execution_id=uuid.uuid4(),
        status=ReasoningEvaluationStatus.EVALUATED,
        hallucination=True,
        data_use_correct=False,
        rationale="r",
        judge_model="m",
        evaluated_at=datetime.now(UTC),
        input_tokens=10,
        output_tokens=2,
    )
    second = AlertReasoningEvaluationRecord(
        **{**first.__dict__, "hallucination": False, "data_use_correct": True}
    )
    table = get_dynamodb_resource().Table(
        ALERT_REASONING_EVALUATIONS_TABLE["TableName"]
    )
    try:
        assert repository.create(first) == first
        assert repository.create(second) == first
        assert repository.get(alert_id) == first
    finally:
        table.delete_item(Key={"alert_id": str(alert_id)})
