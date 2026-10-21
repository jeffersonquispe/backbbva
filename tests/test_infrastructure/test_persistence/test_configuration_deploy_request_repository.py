from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.application.ports.configuration_deploy_request_port import (
    ConfigurationDeployRequest,
)
from src.infrastructure.persistence.database.dynamodb.repositories import (
    configuration_deploy_request_repository as repository_module,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_deploy_request_repository import (
    DynamoConfigurationDeployRequestRepository,
    _to_item,
)


class _FakeTable:
    def __init__(self, item: dict[str, Any]) -> None:
        self.item = item
        self.update_params: dict[str, Any] = {}

    def update_item(self, **kwargs: Any) -> None:
        self.update_params = kwargs
        values = kwargs["ExpressionAttributeValues"]
        self.item.update(
            {
                "status": values[":approved"],
                "approved_by": values[":approved_by"],
                "approved_by_id": values[":approved_by_id"],
                "approved_at": values[":approved_at"],
            }
        )

    def get_item(self, **_: Any) -> dict[str, Any]:
        return {"Item": self.item}


class _FakeResource:
    def __init__(self, table: _FakeTable) -> None:
        self.table = table

    def Table(self, _: str) -> _FakeTable:
        return self.table


def test_approve_defines_the_pending_condition_value(monkeypatch: Any) -> None:
    request = ConfigurationDeployRequest(
        id="request-1",
        target_configuration_id="cfg-1",
        target_version=2,
        current_configuration_id="cfg-1",
        current_version=1,
        title="Promote v2",
        message="Ready for production",
        changes=[],
        requested_by="analyst@example.test",
        requested_at=datetime(2026, 10, 20, tzinfo=UTC),
    )
    table = _FakeTable(_to_item(request))
    monkeypatch.setattr(
        repository_module,
        "get_dynamodb_resource",
        lambda: _FakeResource(table),
    )

    repository = DynamoConfigurationDeployRequestRepository()
    repository.approve(
        request_id=request.id,
        approved_by="manager@example.test",
        approved_at=datetime(2026, 10, 21, tzinfo=UTC),
        approved_by_id="manager-1",
    )

    assert table.update_params["ConditionExpression"] == (
        "attribute_exists(id) AND #status = :pending"
    )
    assert table.update_params["ExpressionAttributeValues"][":pending"] == "pending"
