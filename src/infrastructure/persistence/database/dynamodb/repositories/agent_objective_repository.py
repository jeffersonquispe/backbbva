from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.domain.agents.objective import AgentObjective, AgentObjectiveStatus
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    AGENT_OBJECTIVE_ACTIVE_TABLE,
    AGENT_OBJECTIVES_TABLE,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)


class AgentObjectiveConflictError(Exception):
    pass


class DynamoAgentObjectiveRepository(AgentObjectiveRepository):
    """Version rows and the active pointer use separately keyed tables."""

    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(
            AGENT_OBJECTIVES_TABLE["TableName"]
        )
        self._active_table = get_dynamodb_resource().Table(
            AGENT_OBJECTIVE_ACTIVE_TABLE["TableName"]
        )

    def create(self, objective: AgentObjective) -> AgentObjective:
        if objective.version < 1:
            raise ValueError("objective versions must be positive")
        try:
            self._table.put_item(
                Item=_objective_item(objective),
                ConditionExpression=(
                    "attribute_not_exists(objective_id) AND "
                    "attribute_not_exists(version)"
                ),
            )
        except ClientError as error:
            _raise_conflict(error)
        return objective

    def get(self, objective_id: str, version: int) -> AgentObjective | None:
        item = self._table.get_item(
            Key={"objective_id": objective_id, "version": version}
        ).get("Item")
        if not item or item.get("record_type") == "ACTIVE_POINTER":
            return None
        return _objective_from_item(item)

    def list_versions(self, objective_id: str) -> list[AgentObjective]:
        result = self._table.query(
            KeyConditionExpression=Key("objective_id").eq(objective_id)
            & Key("version").gt(0),
            ScanIndexForward=False,
        )
        return [
            _objective_from_item(item)
            for item in result.get("Items", [])
        ]

    def get_active(self, objective_id: str) -> AgentObjective | None:
        pointer = self._active_table.get_item(
            Key={"objective_id": objective_id}
        ).get("Item")
        active_version = pointer.get("active_version") if pointer else None
        return self.get(objective_id, int(active_version)) if active_version else None

    def activate(
        self,
        objective: AgentObjective,
        *,
        expected_active_version: int | None,
    ) -> AgentObjective:
        if objective.status != AgentObjectiveStatus.ACTIVE or objective.version < 1:
            raise ValueError("only a positive objective version can be activated")
        activated_at = objective.activated_at or datetime.now(UTC)
        try:
            self._table.update_item(
                Key={"objective_id": objective.objective_id, "version": objective.version},
                UpdateExpression=(
                    "SET #status = :active, approved_by = :approved_by, "
                    "activated_at = :activated_at"
                ),
                ConditionExpression="#status = :draft",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":draft": AgentObjectiveStatus.DRAFT.value,
                    ":active": AgentObjectiveStatus.ACTIVE.value,
                    ":approved_by": objective.approved_by or "",
                    ":activated_at": activated_at.isoformat(),
                },
            )
            pointer_item = {
                "objective_id": objective.objective_id,
                "record_type": "ACTIVE_POINTER",
                "active_version": objective.version,
                "updated_at": activated_at.isoformat(),
            }
            pointer_conditions = (
                {
                    "ConditionExpression": "attribute_not_exists(objective_id)"
                }
                if expected_active_version is None
                else {
                    "ConditionExpression": "active_version = :expected",
                    "ExpressionAttributeValues": {
                        ":expected": expected_active_version
                    },
                }
            )
        except ClientError as error:
            _raise_conflict(error)
        try:
            self._active_table.put_item(Item=pointer_item, **pointer_conditions)
        except ClientError as error:
            self._table.update_item(
                Key={"objective_id": objective.objective_id, "version": objective.version},
                UpdateExpression="SET #status = :draft REMOVE approved_by, activated_at",
                ConditionExpression="#status = :active",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":active": AgentObjectiveStatus.ACTIVE.value,
                    ":draft": AgentObjectiveStatus.DRAFT.value,
                },
            )
            _raise_conflict(error)
        if expected_active_version is not None:
            try:
                self._table.update_item(
                    Key={
                        "objective_id": objective.objective_id,
                        "version": expected_active_version,
                    },
                    UpdateExpression="SET #status = :retired",
                    ConditionExpression="#status = :active",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":active": AgentObjectiveStatus.ACTIVE.value,
                        ":retired": AgentObjectiveStatus.RETIRED.value,
                    },
                )
            except ClientError as error:
                if error.response["Error"].get("Code") != "ConditionalCheckFailedException":
                    raise
        return replace(objective, activated_at=activated_at)


def _objective_item(objective: AgentObjective) -> dict[str, Any]:
    value = asdict(objective)
    value["status"] = objective.status.value
    value["primary_metrics"] = list(objective.primary_metrics)
    value["created_at"] = objective.created_at.isoformat()
    value["activated_at"] = (
        objective.activated_at.isoformat() if objective.activated_at else None
    )
    return to_dynamodb(value)


def _objective_from_item(item: dict[str, Any]) -> AgentObjective:
    value = from_dynamodb(item)
    value.pop("record_type", None)
    value["primary_metrics"] = tuple(value["primary_metrics"])
    value["status"] = AgentObjectiveStatus(value["status"])
    value["created_at"] = datetime.fromisoformat(value["created_at"])
    if value.get("activated_at"):
        value["activated_at"] = datetime.fromisoformat(value["activated_at"])
    return AgentObjective(**value)


def _raise_conflict(error: ClientError) -> None:
    code = error.response["Error"].get("Code")
    if code in {"ConditionalCheckFailedException", "TransactionCanceledException"}:
        raise AgentObjectiveConflictError(
            "objective version or active pointer changed"
        ) from error
    raise error
