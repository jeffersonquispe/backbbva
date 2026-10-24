from __future__ import annotations

from dataclasses import dataclass

import src.infrastructure.persistence.database.dynamodb.repositories.model_repository as module
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
    DynamoModelRepository,
)


@dataclass
class InMemoryModel:
    active: bool


class PaginatedTable:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def scan(self, **kwargs: dict) -> dict:
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return {
                "Items": [{"model_id": "inactive"}],
                "LastEvaluatedKey": {"model_id": "inactive"},
            }
        return {"Items": [{"model_id": "active"}]}


def test_get_active_scans_consistently_across_all_pages(monkeypatch) -> None:
    repository = DynamoModelRepository.__new__(DynamoModelRepository)
    table = PaginatedTable()
    repository._table = table
    inactive = InMemoryModel(active=False)
    active = InMemoryModel(active=True)

    def from_item(item: dict[str, str]) -> InMemoryModel:
        return active if item["model_id"] == "active" else inactive

    monkeypatch.setattr(module, "_from_item", from_item)
    assert repository.get_active() is active

    assert table.calls[0] == {"ConsistentRead": True}
    assert table.calls[1] == {
        "ConsistentRead": True,
        "ExclusiveStartKey": {"model_id": "inactive"},
    }
