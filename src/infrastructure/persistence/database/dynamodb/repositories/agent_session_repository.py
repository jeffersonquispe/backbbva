from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionStatus,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "agent_sessions"


class AgentSessionConflictError(Exception):
    """Raised when a concurrent update or lease claim loses its condition."""


class DynamoAgentSessionRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def create(self, session: AgentSession) -> AgentSession:
        item = _to_item(session)
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(session_id)",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AgentSessionConflictError("session already exists") from error
            raise
        return session

    def get(self, session_id: str) -> AgentSession | None:
        item = self._table.get_item(Key={"session_id": session_id}).get("Item")
        return _from_item(item) if item else None

    def list_by_owner(self, owner_id: str, limit: int = 50) -> list[AgentSession]:
        result = self._table.query(
            IndexName="OwnerIdx",
            KeyConditionExpression=Key("owner_id").eq(owner_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [_from_item(item) for item in result.get("Items", [])]

    def list_by_status(
        self, status: AgentSessionStatus, limit: int | None = 50
    ) -> list[AgentSession]:
        items = []
        kwargs = {"IndexName": "StatusIdx", "KeyConditionExpression": Key("status").eq(status.value), "ScanIndexForward": True}
        while True:
            if limit is not None:
                kwargs["Limit"] = max(1, limit - len(items))
            response = self._table.query(**kwargs)
            items.extend(response.get("Items", []))
            cursor = response.get("LastEvaluatedKey")
            if not cursor or (limit is not None and len(items) >= limit):
                break
            kwargs["ExclusiveStartKey"] = cursor
        return [_from_item(item) for item in items]

    def update(self, session: AgentSession, expected_rev: int) -> AgentSession:
        item = _to_item(session)
        item["rev"] = expected_rev + 1
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="rev = :expected",
                ExpressionAttributeValues={":expected": expected_rev},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AgentSessionConflictError("session revision changed") from error
            raise
        return _from_item(item)

    def acquire_lease(
        self, session_id: str, owner: str, now: datetime, expires_at: datetime
    ) -> AgentSession | None:
        try:
            result = self._table.update_item(
                Key={"session_id": session_id},
                UpdateExpression=(
                    "SET lease_owner = :owner, lease_expires_at = :expires, "
                    "updated_at = :now ADD rev :one"
                ),
                ConditionExpression=(
                    "#status = :active AND "
                    "(attribute_not_exists(lease_expires_at) OR lease_expires_at <= :now)"
                ),
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={
                    ":owner": owner,
                    ":expires": expires_at.isoformat(),
                    ":now": now.isoformat(),
                    ":active": AgentSessionStatus.ACTIVE.value,
                    ":one": 1,
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return None
            raise
        attributes = result.get("Attributes")
        return _from_item(attributes) if attributes else None

    def increment_message_seq(self, session_id: str) -> int:
        result = self._table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="ADD message_seq :one, rev :one",
            ConditionExpression="attribute_exists(session_id)",
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(result["Attributes"]["message_seq"])


def _to_item(session: AgentSession) -> dict[str, Any]:
    item = asdict(session)
    item["status"] = session.status.value
    item["created_at"] = session.created_at.isoformat()
    item["updated_at"] = session.updated_at.isoformat()
    item["lease_expires_at"] = (
        session.lease_expires_at.isoformat() if session.lease_expires_at else None
    )
    item["owner_id"] = session.owner_id
    item["baseline_components"] = [
        asdict(reference) for reference in session.baseline_components
    ]
    return {key: value for key, value in item.items() if value is not None}


def _from_item(item: dict[str, Any]) -> AgentSession:
    return AgentSession(
        session_id=item["session_id"],
        mode=item["mode"],
        status=AgentSessionStatus(item["status"]),
        owner_id=item["owner_id"],
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        scope=item.get("scope", {}),
        objective_id=item.get("objective_id"),
        objective_version=(
            int(item["objective_version"])
            if item.get("objective_version") is not None
            else None
        ),
        budget_limits=item.get("budget_limits", {}),
        prompt_versions=item.get("prompt_versions", {}),
        lease_owner=item.get("lease_owner"),
        lease_expires_at=(
            datetime.fromisoformat(item["lease_expires_at"])
            if item.get("lease_expires_at")
            else None
        ),
        rev=int(item.get("rev", 0)),
        message_seq=int(item.get("message_seq", 0)),
        budget_renewals=int(item.get("budget_renewals", 0)),
        baseline_components=tuple(
            ComponentVersionReference(**reference)
            for reference in item.get("baseline_components", [])
        ),
        block=dict(item.get("block", {})),
        candidate_allowance=int(item.get("candidate_allowance", 0)),
        stagnation_reset_after=int(item.get("stagnation_reset_after", 0)),
    )
