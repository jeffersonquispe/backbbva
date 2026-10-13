from datetime import datetime

from src.application.ports.alert_schema_port import (
    AlertSchemaSuggestion,
    AlertSchemaSuggestionRepository,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)


class DynamoAlertSchemaSuggestionRepository(AlertSchemaSuggestionRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("alert_schema_suggestions")

    def create(self, suggestion: AlertSchemaSuggestion) -> AlertSchemaSuggestion:
        self._table.put_item(Item=to_dynamodb({**suggestion.__dict__, "created_at": suggestion.created_at.isoformat()}))
        return suggestion

    def get(self, suggestion_id: str) -> AlertSchemaSuggestion | None:
        item = self._table.get_item(Key={"id": suggestion_id}).get("Item")
        if not item:
            return None
        value = from_dynamodb(item)
        value["created_at"] = datetime.fromisoformat(value["created_at"])
        return AlertSchemaSuggestion(**value)

    def update(self, suggestion: AlertSchemaSuggestion) -> AlertSchemaSuggestion:
        return self.create(suggestion)

    def list(self) -> list[AlertSchemaSuggestion]:
        values = []
        for item in self._table.scan().get("Items", []):
            value = from_dynamodb(item)
            value["created_at"] = datetime.fromisoformat(value["created_at"])
            values.append(AlertSchemaSuggestion(**value))
        return sorted(values, key=lambda item: item.created_at, reverse=True)
