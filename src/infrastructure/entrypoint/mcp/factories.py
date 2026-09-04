from __future__ import annotations

from functools import lru_cache

from src.application.ports.alert_port import AlertRepository
from src.application.ports.model_port import ModelRepository
from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
    DynamoModelRepository,
)
from src.infrastructure.persistence.object_storage.minio import (
    get_model_object_storage,
)


@lru_cache(maxsize=1)
def get_alert_repository() -> AlertRepository:
    return DynamoAlertRepository()


@lru_cache(maxsize=1)
def get_model_repository() -> ModelRepository:
    return DynamoModelRepository()


@lru_cache(maxsize=1)
def get_model_storage() -> ObjectStoragePort:
    return get_model_object_storage()
