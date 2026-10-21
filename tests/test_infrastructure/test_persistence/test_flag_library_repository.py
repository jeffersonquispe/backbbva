from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from src.application.ports.flag_library_port import FlagLibraryRevisionConflict
from src.domain.configurations.entities import FlagType
from src.infrastructure.persistence.database.dynamodb.repositories.flag_library_repository import (
    DynamoFlagLibraryRepository,
)


class ConditionalFailureTable:
    def __init__(self, item: dict) -> None:
        self.item = item
        self.put_request: dict | None = None

    def get_item(self, **kwargs) -> dict:
        return {"Item": self.item}

    def put_item(self, **kwargs) -> None:
        self.put_request = kwargs
        raise ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "stale"}},
            "PutItem",
        )


def test_flag_repository_uses_conditional_update_and_maps_stale_write() -> None:
    now = datetime.now(UTC)
    item = {
        "id": "flag-1",
        "flag_type": FlagType.RED.value,
        "name": "Flag",
        "description": "Before",
        "evolved_variables": [],
        "modus_operandi_library_ids": [],
        "active": True,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "embedding": None,
    }
    table = ConditionalFailureTable(item)
    repository = DynamoFlagLibraryRepository.__new__(DynamoFlagLibraryRepository)
    repository._table = table

    with pytest.raises(FlagLibraryRevisionConflict):
        repository.update("flag-1", name="After", expected_updated_at=now)

    assert table.put_request is not None
    assert "ConditionExpression" in table.put_request
    assert table.put_request["Item"]["updated_at"] != now.isoformat()
