from __future__ import annotations

from datetime import datetime
from uuid import UUID

from boto3.dynamodb.conditions import Key

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)


class DynamoLocalUserRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("users")

    def get_by_email(self, email: str) -> LocalUser | None:
        response = self._table.query(
            IndexName="EmailIdx", KeyConditionExpression=Key("email").eq(email), Limit=1
        )
        items = response.get("Items", [])
        return _from_item(items[0]) if items else None

    def get_by_id(self, user_id: UUID) -> LocalUser | None:
        item = self._table.get_item(Key={"user_id": str(user_id)}).get("Item")
        return _from_item(item) if item else None

    def create(self, user: LocalUser) -> LocalUser:
        self._table.put_item(
            Item=_to_item(user), ConditionExpression="attribute_not_exists(user_id)"
        )
        return user

    def update(self, user: LocalUser) -> LocalUser:
        self._table.put_item(
            Item=_to_item(user), ConditionExpression="attribute_exists(user_id)"
        )
        return user

    def list(self) -> list[LocalUser]:
        kwargs: dict = {}
        users: list[LocalUser] = []
        while True:
            response = self._table.scan(**kwargs)
            users.extend(_from_item(item) for item in response.get("Items", []))
            if "LastEvaluatedKey" not in response:
                return users
            kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def _to_item(user: LocalUser) -> dict:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.name,
        "password_hash": user.password_hash,
        "role": user.role.value,
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat(),
        "updated_at": user.updated_at.isoformat(),
    }


def _from_item(item: dict) -> LocalUser:
    return LocalUser(
        id=UUID(item["user_id"]),
        email=item["email"],
        name=item["name"],
        password_hash=item["password_hash"],
        role=LocalRole(item["role"]),
        is_active=bool(item["is_active"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
    )
