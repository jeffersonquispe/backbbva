from __future__ import annotations

from datetime import datetime

from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)


class DynamoRevokedTokenRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("revoked_tokens")

    def revoke(self, token_id: str, expires_at: datetime) -> None:
        # expires_at is the table's TTL attribute (epoch seconds), so DynamoDB
        # drops the row once the token would have expired on its own.
        self._table.put_item(Item={"jti": token_id, "expires_at": int(expires_at.timestamp())})

    def is_revoked(self, token_id: str) -> bool:
        return "Item" in self._table.get_item(Key={"jti": token_id}, ConsistentRead=True)
