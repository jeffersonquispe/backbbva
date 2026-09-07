from __future__ import annotations

from functools import lru_cache

from src.application.ports.workflow_executor_port import (
    WorkflowExecutionRef,
    WorkflowExecutor,
)
from src.application.ports.workflow_port import WorkflowExecutionRecord
from src.application.use_cases.alerts.curate_alert_to_dataset import (
    CurateAlertToDatasetUseCase,
)
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_alert_field_mapping_repository,
    get_dataset_analysis_dispatcher,
    get_dataset_repository,
    get_dataset_summary_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.feedback_repository import (
    DynamoFeedbackRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowExecutionRepository,
)


class DeferredWorkflowExecutor(WorkflowExecutor):
    def start(
        self,
        workflow: WorkflowExecutionRecord,
    ) -> WorkflowExecutionRef:
        return WorkflowExecutionRef(backend="deferred")


@lru_cache
def get_alert_repository() -> DynamoAlertRepository:
    return DynamoAlertRepository()


@lru_cache
def get_workflow_execution_repository() -> DynamoWorkflowExecutionRepository:
    return DynamoWorkflowExecutionRepository()


@lru_cache
def get_workflow_executor() -> WorkflowExecutor:
    backend = genai_config.ASYNC_EXECUTOR_BACKEND.strip().lower()
    if backend == "celery":
        from src.infrastructure.workflows.celery.executor import (
            CeleryWorkflowExecutor,
        )

        return CeleryWorkflowExecutor()
    if backend == "deferred":
        return DeferredWorkflowExecutor()
    raise ValueError(f"Unsupported workflow executor backend: {backend}")


def get_start_alert_test_workflow_use_case() -> StartAlertTestWorkflowUseCase:
    return StartAlertTestWorkflowUseCase(
        alert_repository=get_alert_repository(),
        async_operation_repository=DynamoAsyncOperationRepository(),
        workflow_repository=get_workflow_execution_repository(),
        workflow_executor=get_workflow_executor(),
    )


@lru_cache
def get_feedback_repository() -> DynamoFeedbackRepository:
    return DynamoFeedbackRepository()


def get_curate_alert_to_dataset_use_case() -> CurateAlertToDatasetUseCase:
    return CurateAlertToDatasetUseCase(
        alert_repository=get_alert_repository(),
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        dispatcher=get_dataset_analysis_dispatcher(),
        mapping_repository=get_alert_field_mapping_repository(),
        feedback_repository=get_feedback_repository(),
        workflow_execution_repository=get_workflow_execution_repository(),
    )
