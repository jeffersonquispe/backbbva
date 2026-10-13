from __future__ import annotations

from functools import lru_cache

from src.application.ports.alert_port import AlertRepository
from src.application.ports.feedback_port import FeedbackRepository
from src.application.ports.workflow_executor_port import (
    WorkflowExecutor,
)
from src.application.ports.workflow_port import WorkflowExecutionRepository
from src.application.use_cases.alerts.curate_alert_to_dataset import (
    CurateAlertToDatasetUseCase,
)
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
    get_async_operation_repository,
)
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_dataset_analysis_dispatcher,
    get_dataset_repository,
    get_dataset_summary_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_repository import (
    DynamoAlertRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.workflow_repository import (
    DynamoWorkflowExecutionRepository,
)
from src.infrastructure.persistence.object_storage.minio import get_object_storage
from src.infrastructure.queues.celery.deferred_executor import (
    DeferredWorkflowExecutor,
)


@lru_cache
def get_alert_repository() -> AlertRepository:
    return DynamoAlertRepository()


@lru_cache
def get_workflow_execution_repository() -> WorkflowExecutionRepository:
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
    # Lazy: metrics_factory imports this module (get_alert_repository).
    from src.infrastructure.entrypoint.api.factories.metrics_factory import (
        get_record_alert_metrics_event_use_case,
    )

    return StartAlertTestWorkflowUseCase(
        alert_repository=get_alert_repository(),
        async_operation_repository=get_async_operation_repository(),
        workflow_repository=get_workflow_execution_repository(),
        workflow_executor=get_workflow_executor(),
        metrics_recorder=get_record_alert_metrics_event_use_case(),
        object_storage=get_object_storage(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


@lru_cache
def get_feedback_repository() -> FeedbackRepository:
    from src.infrastructure.persistence.database.dynamodb.repositories.feedback_repository import (
        DynamoFeedbackRepository,
    )

    return DynamoFeedbackRepository()


def get_curate_alert_to_dataset_use_case() -> CurateAlertToDatasetUseCase:
    return CurateAlertToDatasetUseCase(
        alert_repository=get_alert_repository(),
        dataset_repository=get_dataset_repository(),
        summary_repository=get_dataset_summary_repository(),
        dispatcher=get_dataset_analysis_dispatcher(),
        feedback_repository=get_feedback_repository(),
        workflow_execution_repository=get_workflow_execution_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_alert_object_storage():
    return get_object_storage()
