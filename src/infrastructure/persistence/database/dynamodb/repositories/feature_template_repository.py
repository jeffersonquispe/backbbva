from __future__ import annotations

from datetime import datetime

from src.application.ports.feature_template_port import FeatureTemplate
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)


class DynamoFeatureTemplateRepository:
    def __init__(self):
        self._table = get_dynamodb_resource().Table("feature_templates")

    def create(self, template: FeatureTemplate) -> FeatureTemplate:
        self._table.put_item(
            Item={
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "configuration": to_dynamodb(template.configuration),
                "created_at": template.created_at.isoformat(),
            }
        )
        return template

    def list(self) -> list[FeatureTemplate]:
        items = []
        response = self._table.scan()
        while True:
            items.extend(response.get("Items", []))
            if not response.get("LastEvaluatedKey"):
                break
            response = self._table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        return sorted(
            [
                FeatureTemplate(
                    id=item["id"],
                    name=item["name"],
                    description=item.get("description", ""),
                    configuration=from_dynamodb(item["configuration"]),
                    created_at=datetime.fromisoformat(item["created_at"]),
                )
                for item in items
            ],
            key=lambda entry: entry.created_at,
            reverse=True,
        )

    def delete(self, template_id: str) -> None:
        self._table.delete_item(Key={"id": template_id})
