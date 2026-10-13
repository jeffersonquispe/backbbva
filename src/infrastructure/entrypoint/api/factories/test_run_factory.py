from __future__ import annotations

from functools import lru_cache

from src.application.ports.test_run_port import TestRunRepository
from src.application.ports.workflow_port import WorkflowStepExecutionRepository
from src.application.use_cases.test_runs.delete_test_runs import DeleteTestRunsUseCase
from src.application.use_cases.test_runs.get_test_case_detail import (
    GetTestCaseDetailUseCase,
)
from src.application.use_cases.test_runs.get_test_run import GetTestRunUseCase
from src.application.use_cases.test_runs.list_test_runs import ListTestRunsUseCase
from src.application.use_cases.test_runs.start_test_run import StartTestRunUseCase
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
    get_workflow_execution_repository,
    get_workflow_executor,
)
from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
    get_async_operation_repository,
)
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_dataset_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_repository import (
    DynamoAlertSchemaRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.test_run_repository import (
    DynamoTestRunRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowStepExecutionRepository,
)
from src.infrastructure.persistence.object_storage.minio import get_object_storage


@lru_cache
def get_test_run_repository() -> TestRunRepository:
    return DynamoTestRunRepository()


@lru_cache
def get_workflow_step_execution_repository() -> WorkflowStepExecutionRepository:
    return DynamoWorkflowStepExecutionRepository()


def get_start_test_run_use_case() -> StartTestRunUseCase:
    from src.infrastructure.entrypoint.api.factories.configuration_factory import (
        get_configuration_repository,
    )
    from src.infrastructure.entrypoint.api.factories.metrics_factory import (
        get_record_alert_metrics_event_use_case,
    )

    return StartTestRunUseCase(
        configuration_repository=get_configuration_repository(),
        dataset_repository=get_dataset_repository(),
        test_run_repository=get_test_run_repository(),
        alert_repository=get_alert_repository(),
        async_operation_repository=get_async_operation_repository(),
        workflow_repository=get_workflow_execution_repository(),
        workflow_executor=get_workflow_executor(),
        metrics_recorder=get_record_alert_metrics_event_use_case(),
        schema_repository=DynamoAlertSchemaRepository(),
        object_storage=get_object_storage(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_get_test_run_use_case() -> GetTestRunUseCase:
    return GetTestRunUseCase(
        test_run_repository=get_test_run_repository(),
        workflow_repository=get_workflow_execution_repository(),
        step_repository=get_workflow_step_execution_repository(),
        alert_repository=get_alert_repository(),
        schema_repository=DynamoAlertSchemaRepository(),
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


def get_delete_test_runs_use_case() -> DeleteTestRunsUseCase:
    return DeleteTestRunsUseCase(
        test_run_repository=get_test_run_repository(),
        workflow_repository=get_workflow_execution_repository(),
        step_repository=get_workflow_step_execution_repository(),
        alert_repository=get_alert_repository(),
        async_operation_repository=get_async_operation_repository(),
    )
