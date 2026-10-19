from src.infrastructure.persistence.database.dynamodb.repositories.e2e_state_cleaner import (
    DynamoE2EStateCleaner,
)


class InMemoryTable:
    key_schema = [{"AttributeName": "record_id", "KeyType": "HASH"}]

    def __init__(self, rows):
        self.rows = rows

    def scan(self, **_kwargs):
        return {"Items": list(self.rows)}

    def batch_writer(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def delete_item(self, Key):
        self.rows[:] = [row for row in self.rows if row["record_id"] != Key["record_id"]]


class InMemoryPaginator:
    def __init__(self, names):
        self.names = names

    def paginate(self):
        return [{"TableNames": self.names}]


class InMemoryResource:
    def __init__(self):
        self.tables = {
            "users": [{"record_id": "manager"}],
            "assistant_optimizer_settings": [{"record_id": "current"}],
            "assistant_optimizer_settings_changes": [{"record_id": "current"}],
        }
        self.meta = type(
            "Meta",
            (),
            {"client": type("Client", (), {"get_paginator": lambda _self, _name: InMemoryPaginator(list(self.tables))})()},
        )()

    def Table(self, name):
        return InMemoryTable(self.tables[name])


def test_cleaner_removes_assistant_settings_and_history_but_preserves_users(monkeypatch):
    resource = InMemoryResource()
    monkeypatch.setattr(
        "src.infrastructure.persistence.database.dynamodb.repositories.e2e_state_cleaner.get_dynamodb_resource",
        lambda: resource,
    )

    result = DynamoE2EStateCleaner().clean()

    assert result.deleted_items == 2
    assert result.preserved_tables == ["users"]
    assert resource.tables["users"] == [{"record_id": "manager"}]
    assert resource.tables["assistant_optimizer_settings"] == []
    assert resource.tables["assistant_optimizer_settings_changes"] == []
