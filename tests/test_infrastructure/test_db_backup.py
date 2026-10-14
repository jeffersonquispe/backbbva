from __future__ import annotations

import json

import pytest

from scripts import db_backup

TABLE_SCHEMA = {
    "TableName": "alerts",
    "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    "AttributeDefinitions": [{"AttributeName": "id", "AttributeType": "S"}],
    "BillingModeSummary": {"BillingMode": "PAY_PER_REQUEST"},
}


class InMemoryTable:
    def __init__(self, name: str, rows: list[dict]):
        self.name = name
        self.rows = rows

    def scan(self, **_kwargs):
        return {"Items": self.rows}

    def wait_until_exists(self):
        return None

    def batch_writer(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def put_item(self, Item):
        self.rows.append(Item)


class InMemoryDynamoClient:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.created = []

    def list_tables(self, **_kwargs):
        return {"TableNames": ["alerts"]}

    def describe_table(self, TableName):
        if TableName not in self.created and not self.rows:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "ResourceNotFoundException"}}, "DescribeTable")
        return {"Table": TABLE_SCHEMA}

    def create_table(self, **kwargs):
        self.created.append(kwargs["TableName"])


class InMemoryDynamo:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.client = InMemoryDynamoClient(rows)
        self.meta = type("Meta", (), {"client": self.client})()

    def Table(self, _name):
        return InMemoryTable("alerts", self.rows)


class InMemoryOpenSearchIndices:
    def exists(self, **_kwargs):
        return False


class InMemoryOpenSearch:
    indices = InMemoryOpenSearchIndices()


def test_restore_unwraps_opensearch_settings_before_create(tmp_path, monkeypatch):
    index_dir = tmp_path / "opensearch"
    index_dir.mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps({"dynamodb": {}, "opensearch": {"index": "fraud_knowledge", "documents": 0}})
    )
    (index_dir / "settings.json").write_text(
        json.dumps({"settings": {"index": {"knn": "true", "number_of_shards": "1"}}})
    )
    (index_dir / "mapping.json").write_text(json.dumps({"properties": {}}))
    (index_dir / "documents.jsonl").write_text("")

    class RecordingIndices:
        created = None

        def exists(self, **_kwargs):
            return False

        def create(self, **kwargs):
            self.created = kwargs["body"]

    class RecordingOpenSearch:
        indices = RecordingIndices()

    monkeypatch.setattr(db_backup, "_dynamodb", lambda: type("Dynamo", (), {"meta": type("Meta", (), {"client": type("Client", (), {})()})()})())
    monkeypatch.setattr(db_backup, "_opensearch", RecordingOpenSearch)
    db_backup.restore(tmp_path, skip_object_storage=True, os_bulk_size=20, checkpoint=None, resume=False)
    assert RecordingOpenSearch.indices.created["settings"]["index"]["knn"] == "true"


def test_backup_captures_settings_mapping_and_documents(tmp_path, monkeypatch):
    class RecordingIndices:
        def exists(self, **_kwargs):
            return True

        def get_settings(self, **_kwargs):
            return {"fraud_knowledge": {"settings": {"index": {"knn": "true"}}}}

        def get_mapping(self, **_kwargs):
            return {"fraud_knowledge": {"mappings": {"properties": {}}}}

    class RecordingOpenSearch:
        indices = RecordingIndices()

    empty = InMemoryDynamo([])
    monkeypatch.setattr(empty.meta.client, "list_tables", lambda **_kwargs: {"TableNames": []})
    monkeypatch.setattr(db_backup, "_dynamodb", lambda: empty)
    monkeypatch.setattr(db_backup, "_opensearch", RecordingOpenSearch)
    monkeypatch.setattr(db_backup.helpers, "scan", lambda *_args, **_kwargs: iter([]))
    target = tmp_path / "snapshot"
    db_backup.backup(target, skip_object_storage=True)
    settings = json.loads((target / "opensearch" / "settings.json").read_text())
    assert settings == {"knn": "true"}


def test_backup_writes_manifest_and_restore_replays_items(tmp_path, monkeypatch):
    original_rows = [{"id": "a-1", "count": 2}]
    source = InMemoryDynamo(original_rows.copy())
    monkeypatch.setattr(db_backup, "_dynamodb", lambda: source)
    monkeypatch.setattr(db_backup, "_opensearch", InMemoryOpenSearch)
    target = tmp_path / "snapshot"
    db_backup.backup(target, skip_object_storage=True)

    manifest = json.loads((target / "manifest.json").read_text())
    assert manifest["dynamodb"]["alerts"]["items"] == 1

    restored_rows: list[dict] = []
    restored = InMemoryDynamo(restored_rows)
    monkeypatch.setattr(db_backup, "_dynamodb", lambda: restored)
    db_backup.restore(target, skip_object_storage=True, os_bulk_size=20, checkpoint=None, resume=False)
    assert restored_rows == original_rows


def test_backup_failure_does_not_publish_manifest_or_leave_partial_files(tmp_path, monkeypatch):
    class BrokenDynamo:
        def __init__(self):
            self.meta = type("Meta", (), {"client": self})()

        def list_tables(self):
            raise OSError("DynamoDB unavailable")

    monkeypatch.setattr(db_backup, "_dynamodb", BrokenDynamo)
    target = tmp_path / "snapshot"
    with pytest.raises(OSError, match="DynamoDB unavailable"):
        db_backup.backup(target, skip_object_storage=True)
    assert list(target.iterdir()) == []
    assert not (tmp_path / ".snapshot.incomplete").exists()


def test_restore_rejects_manifest_without_table_files(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"dynamodb": {"alerts": {"items": 0, "schema": "alerts.schema.json"}}}))
    with pytest.raises(SystemExit, match="missing DynamoDB files"):
        db_backup._load_manifest(tmp_path)


def test_restore_rejects_incompatible_table_schema():
    actual = {**TABLE_SCHEMA, "KeySchema": [{"AttributeName": "other", "KeyType": "HASH"}]}
    with pytest.raises(ValueError, match="incompatible KeySchema"):
        db_backup._validate_table_schema("alerts", TABLE_SCHEMA, actual)
