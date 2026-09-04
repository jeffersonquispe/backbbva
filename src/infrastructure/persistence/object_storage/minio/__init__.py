from functools import lru_cache

from src.application.ports.object_storage_port import ObjectStoragePort
from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.object_storage.minio.minio_object_storage_adapter import (
    MinioObjectStorageAdapter,
)


@lru_cache(maxsize=1)
def get_object_storage() -> ObjectStoragePort:
    return MinioObjectStorageAdapter()


@lru_cache(maxsize=1)
def get_dataset_object_storage() -> ObjectStoragePort:
    return MinioObjectStorageAdapter(bucket=genai_config.DATASET_STORAGE_BUCKET)


@lru_cache(maxsize=1)
def get_model_object_storage() -> ObjectStoragePort:
    return MinioObjectStorageAdapter(bucket=genai_config.MODEL_STORAGE_BUCKET)
