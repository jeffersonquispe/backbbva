from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.agent_release_port import AgentReleaseRepository
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.release import (
    AgentRelease,
    AgentReleaseStatus,
    RetrospectiveValidation,
    RetrospectiveValidationStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.schemas import (
    AGENT_RELEASE_ACTIVE_TABLE,
    AGENT_RELEASE_OBSERVATIONS_TABLE,
    AGENT_RELEASES_TABLE,
    AGENT_RETROSPECTIVE_VALIDATIONS_TABLE,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)


class DynamoAgentReleaseRepository(AgentReleaseRepository):
    def __init__(self) -> None:
        resource = get_dynamodb_resource()
        self._validations = resource.Table(
            AGENT_RETROSPECTIVE_VALIDATIONS_TABLE["TableName"]
        )
        self._releases = resource.Table(AGENT_RELEASES_TABLE["TableName"])
        self._observations = resource.Table(
            AGENT_RELEASE_OBSERVATIONS_TABLE["TableName"]
        )
        self._active = resource.Table(AGENT_RELEASE_ACTIVE_TABLE["TableName"])
        self._client = resource.meta.client

    def create_validation(
        self, validation: RetrospectiveValidation
    ) -> RetrospectiveValidation:
        self._validations.put_item(
            Item=to_dynamodb(_validation_item(validation)),
            ConditionExpression="attribute_not_exists(validation_id)",
        )
        return validation

    def get_validation(self, validation_id: str) -> RetrospectiveValidation | None:
        item = self._validations.get_item(
            Key={"validation_id": validation_id}
        ).get("Item")
        return _validation(from_dynamodb(item)) if item else None

    def create_release(self, release: AgentRelease) -> AgentRelease:
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": AGENT_RELEASES_TABLE["TableName"],
                            "Item": to_dynamodb(_release_item(release)),
                            "ConditionExpression": "attribute_not_exists(release_id)",
                        }
                    },
                    {
                        "Put": {
                            "TableName": AGENT_RELEASE_ACTIVE_TABLE["TableName"],
                            "Item": to_dynamodb(
                                {
                                    "slot": "active",
                                    "release_id": release.release_id,
                                }
                            ),
                            "ConditionExpression": "attribute_not_exists(slot)",
                        }
                    },
                ]
            )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                raise ValueError("ACTIVE_RELEASE_EXISTS") from error
            raise
        return release

    def get_release(self, release_id: str) -> AgentRelease | None:
        item = self._releases.get_item(Key={"release_id": release_id}).get("Item")
        return _release(from_dynamodb(item)) if item else None

    def list_releases(
        self, limit: int = 100, statuses: set[str] | None = None
    ) -> list[AgentRelease]:
        requested_statuses = statuses or {item.value for item in AgentReleaseStatus}
        rows: list[dict[str, Any]] = []
        remaining = max(1, min(limit, 200))
        for status in requested_statuses:
            response = self._releases.query(
                IndexName="StatusRequestedIdx",
                KeyConditionExpression=Key("status").eq(status),
                ScanIndexForward=False,
                Limit=remaining,
            )
            rows.extend(response.get("Items", []))
            if len(rows) >= remaining:
                break
        decoded = [from_dynamodb(item) for item in rows]
        decoded.sort(key=lambda item: item["requested_at"], reverse=True)
        return [_release(item) for item in decoded[:remaining]]

    def update_release(
        self, release: AgentRelease, *, expected_version: int
    ) -> AgentRelease:
        try:
            put = {
                "Put": {
                    "TableName": AGENT_RELEASES_TABLE["TableName"],
                    "Item": to_dynamodb(_release_item(release)),
                    "ConditionExpression": "version = :version",
                    "ExpressionAttributeValues": to_dynamodb(
                        {":version": expected_version}
                    ),
                }
            }
            if release.status is AgentReleaseStatus.ROLLED_BACK:
                self._client.transact_write_items(
                    TransactItems=[
                        put,
                        {
                            "Delete": {
                                "TableName": AGENT_RELEASE_ACTIVE_TABLE["TableName"],
                                "Key": to_dynamodb({"slot": "active"}),
                                "ConditionExpression": "release_id = :release_id",
                                "ExpressionAttributeValues": to_dynamodb(
                                    {":release_id": release.release_id}
                                ),
                            }
                        },
                    ]
                )
            else:
                self._releases.put_item(
                    Item=to_dynamodb(_release_item(release)),
                    ConditionExpression="version = :version",
                    ExpressionAttributeValues=to_dynamodb(
                        {":version": expected_version}
                    ),
                )
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ValueError("VERSION_CONFLICT") from error
            raise
        return release

    def record_observation(
        self, release_id: str, observation_id: str, *, disagreement: bool
    ) -> bool:
        digest = sha256(observation_id.encode()).hexdigest()
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": AGENT_RELEASE_OBSERVATIONS_TABLE["TableName"],
                            "Item": to_dynamodb(
                                {
                                    "release_id": release_id,
                                    "observation_id": digest,
                                    "disagreement": disagreement,
                                }
                            ),
                            "ConditionExpression": "attribute_not_exists(release_id)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": AGENT_RELEASES_TABLE["TableName"],
                            "Key": to_dynamodb({"release_id": release_id}),
                            "UpdateExpression": (
                                "SET observation_count = if_not_exists(observation_count, :zero) + :one, "
                                "disagreement_count = if_not_exists(disagreement_count, :zero) + :disagreement"
                            ),
                            "ConditionExpression": "#status IN (:shadow, :canary5, :canary25, :canary50, :full)",
                            "ExpressionAttributeNames": {"#status": "status"},
                            "ExpressionAttributeValues": to_dynamodb(
                                {
                                    ":zero": 0,
                                    ":one": 1,
                                    ":disagreement": int(disagreement),
                                    ":shadow": AgentReleaseStatus.SHADOW.value,
                                    ":canary5": AgentReleaseStatus.CANARY_5.value,
                                    ":canary25": AgentReleaseStatus.CANARY_25.value,
                                    ":canary50": AgentReleaseStatus.CANARY_50.value,
                                    ":full": AgentReleaseStatus.FULL.value,
                                }
                            ),
                        }
                    },
                ]
            )
            return True
        except ClientError as error:
            existing = self._observations.get_item(
                Key={"release_id": release_id, "observation_id": digest}
            ).get("Item")
            if existing:
                return False
            if error.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                raise ValueError("RELEASE_NOT_SHADOWING") from error
            raise


def _validation_item(validation: RetrospectiveValidation) -> dict[str, Any]:
    return {
        **asdict(validation),
        "status": validation.status.value,
        "component_pins": [_pin_item(pin) for pin in validation.component_pins],
        "baseline_component_pins": [
            _pin_item(pin) for pin in validation.baseline_component_pins
        ],
        "created_at": validation.created_at.isoformat(),
    }


def _release_item(release: AgentRelease) -> dict[str, Any]:
    return {
        **asdict(release),
        "status": release.status.value,
        "candidate_component_pins": [
            _pin_item(pin) for pin in release.candidate_component_pins
        ],
        "previous_component_pins": [
            _pin_item(pin) for pin in release.previous_component_pins
        ],
        "requested_at": release.requested_at.isoformat(),
        "approved_at": release.approved_at.isoformat()
        if release.approved_at
        else None,
        "updated_at": release.updated_at.isoformat() if release.updated_at else None,
        "observation_count": int(release.observations.get("count", 0)),
        "disagreement_count": int(release.observations.get("disagreements", 0)),
    }


def _pin_item(pin: ComponentVersionReference) -> dict[str, str]:
    return asdict(pin)


def _pins(items: list[dict[str, Any]]) -> tuple[ComponentVersionReference, ...]:
    return tuple(ComponentVersionReference(**item) for item in items)


def _validation(item: dict[str, Any]) -> RetrospectiveValidation:
    return RetrospectiveValidation(
        validation_id=item["validation_id"],
        session_id=item["session_id"],
        experiment_id=item["experiment_id"],
        status=RetrospectiveValidationStatus(item["status"]),
        snapshot_id=item["snapshot_id"],
        snapshot_sha256=item["snapshot_sha256"],
        component_pins=_pins(item["component_pins"]),
        baseline_component_pins=_pins(item["baseline_component_pins"]),
        evidence=item["evidence"],
        created_by=item["created_by"],
        created_by_id=item["created_by_id"],
        created_at=datetime.fromisoformat(item["created_at"]),
        error_code=item.get("error_code"),
    )


def _release(item: dict[str, Any]) -> AgentRelease:
    return AgentRelease(
        release_id=item["release_id"],
        validation_id=item["validation_id"],
        session_id=item["session_id"],
        experiment_id=item["experiment_id"],
        status=AgentReleaseStatus(item["status"]),
        candidate_component_pins=_pins(item["candidate_component_pins"]),
        previous_component_pins=_pins(item["previous_component_pins"]),
        requested_by=item["requested_by"],
        requested_by_id=item["requested_by_id"],
        requested_at=datetime.fromisoformat(item["requested_at"]),
        title=item["title"],
        reason=item["reason"],
        snapshot_id=item.get("snapshot_id", ""),
        snapshot_sha256=item.get("snapshot_sha256", ""),
        rollout_policy_version=item.get(
            "rollout_policy_version", "h12_model_only_v1"
        ),
        version=int(item.get("version", 1)),
        approved_by=item.get("approved_by"),
        approved_by_id=item.get("approved_by_id"),
        approved_at=datetime.fromisoformat(item["approved_at"])
        if item.get("approved_at")
        else None,
        updated_at=datetime.fromisoformat(item["updated_at"])
        if item.get("updated_at")
        else None,
        observations={
            "count": int(item.get("observation_count", 0)),
            "disagreements": int(item.get("disagreement_count", 0)),
        },
        rollback_reason=item.get("rollback_reason"),
    )
