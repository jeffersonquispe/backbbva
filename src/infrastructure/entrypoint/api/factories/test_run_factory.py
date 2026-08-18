from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.application.use_cases.test_runs.get_test_case_detail import (
    GetTestCaseDetailUseCase,
)
from src.application.use_cases.test_runs.get_test_run import GetTestRunUseCase
from src.application.use_cases.test_runs.list_datasets import ListDatasetsUseCase
from src.application.use_cases.test_runs.list_test_runs import ListTestRunsUseCase
from src.application.use_cases.test_runs.start_test_run import StartTestRunUseCase
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
    get_workflow_execution_repository,
    get_workflow_executor,
)
from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
    get_async_operation_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.test_run_repository import (
    DynamoTestRunRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowStepExecutionRepository,
)
from src.infrastructure.persistence.dataset.filesystem.csv_dataset_repository import (
    FilesystemCsvDatasetRepository,
)


@lru_cache
def get_test_run_repository() -> DynamoTestRunRepository:
    return DynamoTestRunRepository()


@lru_cache
def get_workflow_step_execution_repository() -> DynamoWorkflowStepExecutionRepository:
    return DynamoWorkflowStepExecutionRepository()


@lru_cache
def get_dataset_repository() -> FilesystemCsvDatasetRepository:
    return FilesystemCsvDatasetRepository(Path(genai_config.DATASETS_DIR))


def get_start_test_run_use_case() -> StartTestRunUseCase:
    return StartTestRunUseCase(
        dataset_repository=get_dataset_repository(),
        test_run_repository=get_test_run_repository(),
        alert_repository=get_alert_repository(),
        async_operation_repository=get_async_operation_repository(),
        workflow_repository=get_workflow_execution_repository(),
        workflow_executor=get_workflow_executor(),
    )


def get_get_test_run_use_case() -> GetTestRunUseCase:
    return GetTestRunUseCase(
        test_run_repository=get_test_run_repository(),
        workflow_repository=get_workflow_execution_repository(),
        step_repository=get_workflow_step_execution_repository(),
    )


def get_list_test_runs_use_case() -> ListTestRunsUseCase:
    return ListTestRunsUseCase(
        get_test_run_repository(), get_workflow_execution_repository()
    )


def get_get_test_case_detail_use_case() -> GetTestCaseDetailUseCase:
    return GetTestCaseDetailUseCase(
        workflow_repository=get_workflow_execution_repository(),
        step_repository=get_workflow_step_execution_repository(),
    )


def get_list_datasets_use_case() -> ListDatasetsUseCase:
    return ListDatasetsUseCase(get_dataset_repository())
