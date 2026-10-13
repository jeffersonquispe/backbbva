from datetime import datetime

from src.application.ports.backup_catalog_port import (
    BackupRecord,
    BackupStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "backups"


class DynamoBackupCatalogRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    @staticmethod
    def _record(item: dict) -> BackupRecord:
        return BackupRecord(
            backup_id=item["backup_id"],
            directory=item["directory"],
            requested_by=item["requested_by"],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            status=BackupStatus(item["status"]),
            error=item.get("error"),
            dynamodb_items=item.get("dynamodb_items"),
            opensearch_documents=item.get("opensearch_documents"),
            object_storage_objects=item.get("object_storage_objects"),
        )

    @staticmethod
    def _item(record: BackupRecord) -> dict:
        item = {
            "backup_id": record.backup_id,
            "directory": record.directory,
            "requested_by": record.requested_by,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "status": record.status.value,
        }
        for field in (
            "error",
            "dynamodb_items",
            "opensearch_documents",
            "object_storage_objects",
        ):
            value = getattr(record, field)
            if value is not None:
                item[field] = value
        return item

    def create(self, record: BackupRecord) -> BackupRecord:
        self._table.put_item(Item=self._item(record), ConditionExpression="attribute_not_exists(backup_id)")
        return record

    def get(self, backup_id: str) -> BackupRecord | None:
        item = self._table.get_item(Key={"backup_id": backup_id}).get("Item")
        return self._record(item) if item else None

    def update(self, record: BackupRecord) -> BackupRecord:
        self._table.put_item(Item=self._item(record))
        return record

    def list(self) -> list[BackupRecord]:
        items: list[dict] = []
        response = self._table.scan()
        items.extend(response.get("Items", []))
        while response.get("LastEvaluatedKey"):
            response = self._table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))
        return sorted(
            (self._record(item) for item in items),
            key=lambda record: record.created_at,
            reverse=True,
        )
