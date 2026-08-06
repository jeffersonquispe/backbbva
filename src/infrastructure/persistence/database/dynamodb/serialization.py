from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_dynamodb(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: to_dynamodb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_dynamodb(item) for item in value]
    return value


def from_dynamodb(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {key: from_dynamodb(item) for key, item in value.items()}
    if isinstance(value, list):
        return [from_dynamodb(item) for item in value]
    return value
