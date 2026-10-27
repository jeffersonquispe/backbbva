from __future__ import annotations

from src.application.ports.alert_schema_port import (
    AlertSchemaStatus,
    AlertSchemaVersion,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_repository import (
    DynamoAlertSchemaRepository,
    _to_item,
)


class PaginatedTable:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []

    def scan(self, **kwargs):
        self.calls.append(dict(kwargs))
        return next(self.pages)


def _repository(pages):
    repository = DynamoAlertSchemaRepository.__new__(DynamoAlertSchemaRepository)
    table = PaginatedTable(pages)
    repository._table = table
    return repository, table


def _item(version, status=AlertSchemaStatus.HISTORICAL):
    return _to_item(
        AlertSchemaVersion(version=version, fields=[], field_roles={}, status=status)
    )


def test_active_schema_is_found_after_an_empty_filtered_page():
    repository, table = _repository(
        [
            {"Items": [], "LastEvaluatedKey": {"version": 61}},
            {"Items": [_item(62, AlertSchemaStatus.ACTIVE)]},
        ]
    )

    assert repository.get_active().version == 62
    assert table.calls[0]["ConsistentRead"] is True
    assert table.calls[1] == {**table.calls[0], "ExclusiveStartKey": {"version": 61}}
    assert table.calls[1]["FilterExpression"] == "#status = :active"


def test_all_schema_versions_are_listed_in_descending_order_across_pages():
    repository, table = _repository(
        [
            {"Items": [_item(60), _item(1)], "LastEvaluatedKey": {"version": 1}},
            {"Items": [_item(62, AlertSchemaStatus.ACTIVE), _item(61)]},
        ]
    )

    assert [schema.version for schema in repository.list_versions()] == [62, 61, 60, 1]
    assert table.calls == [
        {"ConsistentRead": True},
        {"ConsistentRead": True, "ExclusiveStartKey": {"version": 1}},
    ]


def test_missing_active_schema_exhausts_all_pages():
    repository, table = _repository(
        [
            {"Items": [], "LastEvaluatedKey": {"version": 61}},
            {"Items": []},
        ]
    )
    assert repository.get_active() is None
    assert len(table.calls) == 2
