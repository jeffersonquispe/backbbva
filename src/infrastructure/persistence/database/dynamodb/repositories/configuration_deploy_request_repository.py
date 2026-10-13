from __future__ import annotations

from datetime import datetime

from src.application.ports.configuration_deploy_request_port import (
    ConfigurationDeployRequest,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

TABLE_NAME = "configuration_deploy_requests"


class DynamoConfigurationDeployRequestRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def create(self, request: ConfigurationDeployRequest) -> ConfigurationDeployRequest:
        self._table.put_item(Item=to_dynamodb(_to_item(request)))
        return request

    def list(self) -> list[ConfigurationDeployRequest]:
        result = self._table.scan()
        items = result.get("Items", [])
        while "LastEvaluatedKey" in result:
            result = self._table.scan(ExclusiveStartKey=result["LastEvaluatedKey"])
            items.extend(result.get("Items", []))
        return sorted(
            (_from_item(item) for item in items),
            key=lambda item: item.requested_at,
            reverse=True,
        )

    def get(self, request_id: str) -> ConfigurationDeployRequest | None:
        item = self._table.get_item(Key={"id": request_id}).get("Item")
        return _from_item(item) if item else None

    def approve(
        self,
        request_id: str,
        approved_by: str,
        approved_at: datetime,
        approved_by_id: str | None = None,
    ) -> ConfigurationDeployRequest:
        self._table.update_item(
            Key={"id": request_id},
            UpdateExpression="SET #status = :approved, approved_by = :approved_by, approved_by_id = :approved_by_id, approved_at = :approved_at",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=to_dynamodb(
                {
                    ":approved": "approved",
                    ":approved_by": approved_by,
                    ":approved_by_id": approved_by_id,
                    ":approved_at": approved_at.isoformat(),
                }
            ),
            ConditionExpression="attribute_exists(id) AND #status = :pending",
        )
        result = self.get(request_id)
        assert result is not None
        return result


def _to_item(request: ConfigurationDeployRequest) -> dict:
    return {
        "id": request.id,
        "target_configuration_id": request.target_configuration_id,
        "target_version": request.target_version,
        "current_configuration_id": request.current_configuration_id,
        "current_version": request.current_version,
        "title": request.title,
        "message": request.message,
        "changes": request.changes,
        "requested_by": request.requested_by,
        "requested_by_id": request.requested_by_id,
        "requested_at": request.requested_at.isoformat(),
        "status": request.status,
        "approved_by": request.approved_by,
        "approved_by_id": request.approved_by_id,
        "approved_at": request.approved_at.isoformat() if request.approved_at else None,
    }


def _from_item(item: dict) -> ConfigurationDeployRequest:
    value = from_dynamodb(item)
    return ConfigurationDeployRequest(
        id=value["id"],
        target_configuration_id=value["target_configuration_id"],
        target_version=int(value["target_version"]),
        current_configuration_id=value.get("current_configuration_id"),
        current_version=int(value["current_version"])
        if value.get("current_version") is not None
        else None,
        title=value["title"],
        message=value["message"],
        changes=value.get("changes", []),
        requested_by=value["requested_by"],
        requested_by_id=value.get("requested_by_id"),
        requested_at=datetime.fromisoformat(value["requested_at"]),
        status=value.get("status", "pending"),
        approved_by=value.get("approved_by"),
        approved_by_id=value.get("approved_by_id"),
        approved_at=datetime.fromisoformat(value["approved_at"])
        if value.get("approved_at")
        else None,
    )
