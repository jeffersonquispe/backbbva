from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from src.application.ports.configuration_port import ConfigurationRef
from src.application.ports.test_run_port import (
    TestRunConfig,
    TestRunRecord,
    TestRunRepository,
    TestRunStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TEST_RUNS_TABLE_NAME = "test_runs"


class DynamoTestRunRepository(TestRunRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TEST_RUNS_TABLE_NAME)

    def create(self, run: TestRunRecord) -> TestRunRecord:
        self._table.put_item(Item=_to_item(run))
        return run

    def get(self, run_id: UUID) -> TestRunRecord | None:
        response = self._table.get_item(Key={"test_run_id": str(run_id)})
        item = response.get("Item")
        if item is None:
            return None
        return _from_item(item)

    def update(
        self,
        run_id: UUID,
        *,
        status: TestRunStatus | None = None,
        finished_at: datetime | None = None,
    ) -> TestRunRecord | None:
        current = self.get(run_id)
        if current is None:
            return None
        updated = TestRunRecord(
            id=current.id,
            name=current.name,
            dataset_name=current.dataset_name,
            config=current.config,
            status=status or current.status,
            total=current.total,
            created_at=current.created_at,
            updated_at=datetime.now(UTC),
            finished_at=finished_at or current.finished_at,
        )
        self._table.put_item(Item=_to_item(updated))
        return updated

    def list(self) -> list[TestRunRecord]:
        response = self._table.scan()
        return [_from_item(item) for item in response.get("Items", [])]

    def delete(self, run_id: UUID) -> None:
        self._table.delete_item(Key={"test_run_id": str(run_id)})


def _to_item(run: TestRunRecord) -> dict[str, Any]:
    return {
        "test_run_id": str(run.id),
        "name": run.name,
        "dataset_name": run.dataset_name,
        "prompt_overrides": run.config.prompt_overrides,
        "model_overrides": run.config.model_overrides,
        "max_feedback_iterations": run.config.max_feedback_iterations,
        "configuration_ref": (
            {
                "configuration_id": run.config.configuration_ref.configuration_id,
                "version": run.config.configuration_ref.version,
            }
            if run.config.configuration_ref is not None
            else None
        ),
        "schema_version": run.config.schema_version,
        "status": run.status.value,
        "total": run.total,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


def _from_item(item: dict[str, Any]) -> TestRunRecord:
    finished_at = item.get("finished_at")
    configuration_ref = item.get("configuration_ref")
    return TestRunRecord(
        id=UUID(item["test_run_id"]),
        name=item["name"],
        dataset_name=item["dataset_name"],
        config=TestRunConfig(
            prompt_overrides=dict(item.get("prompt_overrides") or {}),
            model_overrides=dict(item.get("model_overrides") or {}),
            # Older items predate this field entirely - fall back to the
            # dataclass's own default rather than duplicating that magic
            # number here.
            max_feedback_iterations=int(
                item.get("max_feedback_iterations", TestRunConfig().max_feedback_iterations)
            ),
            # Older items predate this field entirely - None, same as the
            # dataclass default (test against whatever is active).
            configuration_ref=(
                ConfigurationRef(
                    configuration_id=configuration_ref["configuration_id"],
                    version=int(configuration_ref["version"]),
                )
                if configuration_ref is not None
                else None
            ),
            schema_version=(int(item["schema_version"]) if item.get("schema_version") is not None else None),
        ),
        status=TestRunStatus(item["status"]),
        total=int(item.get("total") or 0),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        finished_at=datetime.fromisoformat(finished_at) if finished_at else None,
    )
