from functools import lru_cache

from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.persistence.object_storage.minio.minio_object_storage_adapter import (
    MinioObjectStorageAdapter,
)


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStoragePort:
    return MinioObjectStorageAdapter()
