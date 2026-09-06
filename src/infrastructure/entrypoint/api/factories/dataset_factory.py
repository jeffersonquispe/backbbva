from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_port import DatasetRepository
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase
from src.application.use_cases.datasets.get_dataset_summary import (
    GetDatasetSummaryUseCase,
)
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase
from src.application.use_cases.test_runs.list_datasets import ListDatasetsUseCase
from src.infrastructure.core.config import genai_config
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_sample_repository import (
    DynamoDatasetSampleRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_summary_repository import (
    DynamoDatasetSummaryRepository,
)
from src.infrastructure.persistence.dataset.filesystem.csv_dataset_repository import (
    FilesystemCsvDatasetRepository,
)
from src.infrastructure.persistence.dataset.minio.csv_dataset_repository import (
    MinioCsvDatasetRepository,
)
from src.infrastructure.persistence.object_storage.minio import (
    get_dataset_object_storage,
)


@lru_cache
def get_dataset_repository() -> DatasetRepository:
    if genai_config.DATASET_STORAGE_BACKEND == "minio":
        return MinioCsvDatasetRepository(get_dataset_object_storage())
    return FilesystemCsvDatasetRepository(Path(genai_config.DATASETS_DIR))


@lru_cache
def get_dataset_summary_repository() -> DynamoDatasetSummaryRepository:
    return DynamoDatasetSummaryRepository()


@lru_cache
def get_dataset_sample_repository() -> DynamoDatasetSampleRepository:
    return DynamoDatasetSampleRepository()


@lru_cache
def get_dataset_analysis_dispatcher() -> DatasetAnalysisDispatcher:
    # Lazy import - keeps celery out of the API process's import graph
    # until a dataset is actually uploaded, matching the
    # ASYNC_EXECUTOR_BACKEND/WorkflowExecutor factories' lazy-import
    # pattern (alert_factory.py, async_operation_factory.py).
    from src.infrastructure.queues.celery.dataset_analysis_dispatcher import (
        CeleryDatasetAnalysisDispatcher,
    )

    return CeleryDatasetAnalysisDispatcher()


def get_list_datasets_use_case() -> ListDatasetsUseCase:
    return ListDatasetsUseCase(get_dataset_repository())


def get_upload_dataset_use_case() -> UploadDatasetUseCase:
    return UploadDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        dispatcher=get_dataset_analysis_dispatcher(),
    )


def get_get_dataset_summary_use_case() -> GetDatasetSummaryUseCase:
    return GetDatasetSummaryUseCase(
        get_dataset_summary_repository(), get_dataset_repository()
    )


def get_delete_dataset_use_case() -> DeleteDatasetUseCase:
    return DeleteDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        sample_repository=get_dataset_sample_repository(),
        summary_repository=get_dataset_summary_repository(),
    )
