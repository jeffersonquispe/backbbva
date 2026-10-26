from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.application.ports.alert_field_mapping_port import AlertFieldMappingRepository
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import DatasetSampleRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.use_cases.datasets.analyze_dataset_on_demand import (
    AnalyzeDatasetOnDemandUseCase,
)
from src.application.use_cases.datasets.analyze_fraud_marking import (
    AnalyzeFraudMarkingUseCase,
)
from src.application.use_cases.datasets.append_dataset_rows import (
    AppendDatasetRowsUseCase,
)
from src.application.use_cases.datasets.create_empty_dataset import (
    CreateEmptyDatasetUseCase,
)
from src.application.use_cases.datasets.delete_alert_field_mapping import (
    DeleteAlertFieldMappingUseCase,
)
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase
from src.application.use_cases.datasets.extract_dataset import ExtractDatasetUseCase
from src.application.use_cases.datasets.get_alert_field_mapping import (
    GetAlertFieldMappingUseCase,
)
from src.application.use_cases.datasets.get_dataset_rows import GetDatasetRowsUseCase
from src.application.use_cases.datasets.get_dataset_summary import (
    GetDatasetSummaryUseCase,
)
from src.application.use_cases.datasets.get_dataset_template import (
    GetDatasetTemplateUseCase,
)
from src.application.use_cases.datasets.save_alert_field_mapping import (
    SaveAlertFieldMappingUseCase,
)
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase
from src.application.use_cases.datasets.upload_dataset_chunks import (
    DatasetUploadChunksUseCase,
)
from src.application.use_cases.test_runs.list_datasets import ListDatasetsUseCase
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
    get_async_operation_repository,
)
from src.infrastructure.monitoring.audit_collector import record_audit
from src.infrastructure.persistence.database.dynamodb.repositories.alert_field_mapping_repository import (
    DynamoAlertFieldMappingRepository,
)
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
    return FilesystemCsvDatasetRepository(
        Path(genai_config.DATASETS_DIR), audit=record_audit
    )


@lru_cache
def get_dataset_summary_repository() -> DatasetSummaryRepository:
    return DynamoDatasetSummaryRepository()


@lru_cache
def get_dataset_sample_repository() -> DatasetSampleRepository:
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
    return ListDatasetsUseCase(
        get_dataset_repository(), get_dataset_summary_repository()
    )


def get_upload_dataset_use_case() -> UploadDatasetUseCase:
    return UploadDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        dispatcher=get_dataset_analysis_dispatcher(),
        async_operation_repository=get_async_operation_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_upload_dataset_chunks_use_case() -> DatasetUploadChunksUseCase:
    return DatasetUploadChunksUseCase(
        storage=get_dataset_object_storage(),
        datasets=get_dataset_repository(),
        upload_dataset=get_upload_dataset_use_case(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_get_dataset_summary_use_case() -> GetDatasetSummaryUseCase:
    return GetDatasetSummaryUseCase(
        get_dataset_summary_repository(), get_dataset_repository()
    )


def get_analyze_fraud_marking_use_case() -> AnalyzeFraudMarkingUseCase:
    return AnalyzeFraudMarkingUseCase(
        get_dataset_repository(),
        get_dataset_summary_repository(),
        get_async_operation_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_delete_dataset_use_case() -> DeleteDatasetUseCase:
    return DeleteDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        sample_repository=get_dataset_sample_repository(),
        summary_repository=get_dataset_summary_repository(),
        async_operation_repository=get_async_operation_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_create_empty_dataset_use_case() -> CreateEmptyDatasetUseCase:
    return CreateEmptyDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        clock=get_clock(),
    )


def get_extract_dataset_use_case() -> ExtractDatasetUseCase:
    return ExtractDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        dispatcher=get_dataset_analysis_dispatcher(),
        clock=get_clock(),
    )


def get_append_dataset_rows_use_case() -> AppendDatasetRowsUseCase:
    return AppendDatasetRowsUseCase(
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        dispatcher=get_dataset_analysis_dispatcher(),
        clock=get_clock(),
    )


def get_analyze_dataset_on_demand_use_case() -> AnalyzeDatasetOnDemandUseCase:
    return AnalyzeDatasetOnDemandUseCase(
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        dispatcher=get_dataset_analysis_dispatcher(),
        async_operation_repository=get_async_operation_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_get_dataset_rows_use_case() -> GetDatasetRowsUseCase:
    return GetDatasetRowsUseCase(
        get_dataset_repository(), get_dataset_summary_repository()
    )


def get_get_dataset_template_use_case() -> GetDatasetTemplateUseCase:
    return GetDatasetTemplateUseCase(get_dataset_repository())


@lru_cache
def get_alert_field_mapping_repository() -> AlertFieldMappingRepository:
    return DynamoAlertFieldMappingRepository()


def get_get_alert_field_mapping_use_case() -> GetAlertFieldMappingUseCase:
    return GetAlertFieldMappingUseCase(get_alert_field_mapping_repository())


def get_delete_alert_field_mapping_use_case() -> DeleteAlertFieldMappingUseCase:
    return DeleteAlertFieldMappingUseCase(get_alert_field_mapping_repository())


def get_save_alert_field_mapping_use_case() -> SaveAlertFieldMappingUseCase:
    return SaveAlertFieldMappingUseCase(
        get_alert_field_mapping_repository(), clock=get_clock()
    )
