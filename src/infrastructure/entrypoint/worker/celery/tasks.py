from __future__ import annotations

import base64
from dataclasses import asdict
from typing import Any
from uuid import UUID

from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
)
from src.application.dtos.document_analyst_decision_dtos import (
    DocumentAnalystDecisionInput,
)
from src.application.dtos.escalate_alert_dtos import (
    EscalateAlertToAnalystInput,
)
from src.application.dtos.execute_alert_action_dtos import (
    ExecuteAlertActionInput,
)
from src.application.use_cases.alerts.document_analyst_decision import (
    DocumentAnalystDecisionUseCase,
)
from src.application.use_cases.alerts.escalate_alert_to_analyst import (
    EscalateAlertToAnalystUseCase,
)
from src.application.use_cases.alerts.execute_alert_action import (
    ExecuteAlertActionUseCase,
)
from src.application.use_cases.async_operations.reconcile_async_operations import (
    ReconcileAsyncOperationsUseCase,
)
from src.application.use_cases.datasets.analyze_dataset import AnalyzeDatasetUseCase
from src.infrastructure.alert_actions.mock.alert_channel_action_adapter import (
    MockAlertChannelActionAdapter,
)
from src.infrastructure.aric.mock.aric_alert_adapter import MockAricAlertAdapter
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.async_operation_repository import (
    DynamoAsyncOperationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_sample_repository import (
    DynamoDatasetSampleRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_summary_repository import (
    DynamoDatasetSummaryRepository,
)
from src.infrastructure.persistence.dataset.minio.csv_dataset_repository import (
    MinioCsvDatasetRepository,
)
from src.infrastructure.persistence.object_storage.minio import (
    get_dataset_object_storage,
    get_object_storage,
)
from src.infrastructure.entrypoint.worker.celery.celery_app import app
from src.infrastructure.queues.celery.inspector import (
    CeleryAsyncExecutionInspector,
)
from src.domain.configurations.exceptions import ConfigurationNotFoundError
from src.infrastructure.workflows.celery.alert_review_workflow import (
    AdversarialFeedbackLimitExceededError,
    AlertReviewWorkflowRunner,
)


@app.task(name="queue.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "backend": "celery"}


@app.task(name="async_operations.run")
def run_async_operation(operation_id: str) -> dict[str, str]:
    repository = DynamoAsyncOperationRepository()
    operation_uuid = UUID(operation_id)

    operation = repository.update(
        operation_uuid,
        status=AsyncOperationStatus.RUNNING,
    )
    if operation is None:
        return {"status": "not_found", "operation_id": operation_id}

    repository.update(
        operation_uuid,
        status=AsyncOperationStatus.SUCCEEDED,
        result={
            "message": "Async operation executed by celery worker",
            "operation_type": operation.operation_type,
        },
    )
    return {"status": "ok", "operation_id": operation_id}


@app.task(name="async_operations.reconcile")
def reconcile_async_operations(limit: int = 100) -> dict:
    use_case = ReconcileAsyncOperationsUseCase(
        repository=DynamoAsyncOperationRepository(),
        inspector=CeleryAsyncExecutionInspector(),
    )
    output = use_case.execute(ReconcileAsyncOperationsInput(limit=limit))
    return {
        "inspected": output.inspected,
        "updated": output.updated,
        "operations": [
            {
                "id": str(operation.id),
                "previous_status": operation.previous_status.value,
                "current_status": operation.current_status.value,
                "execution_state": operation.execution_state.value,
                "detail": operation.detail,
            }
            for operation in output.operations
        ],
    }


_ALERT_REVIEW_MAX_RETRIES = 3


@app.task(
    bind=True,
    name="workflows.alert_review.run",
    autoretry_for=(Exception,),
    dont_autoretry_for=(
        AdversarialFeedbackLimitExceededError,
        ConfigurationNotFoundError,
    ),
    retry_backoff=True,
    retry_kwargs={"max_retries": _ALERT_REVIEW_MAX_RETRIES},
)
def run_alert_review_workflow(self, workflow_execution_id: str) -> dict:
    # autoretry re-runs this whole task from scratch on every attempt, so
    # escalate-to-analyst (fired from a pre_process failure) must only be
    # dispatched on the last one - otherwise a permanently missing field
    # dispatches one escalation per retry instead of one per alert.
    # AdversarialFeedbackLimitExceededError is excluded from autoretry: it
    # already means "classification looped to its cap, escalate" - retrying
    # would just re-run pre_process/classification/adversarial from scratch
    # and burn tokens for a result the internal loop already decided.
    # ConfigurationNotFoundError is excluded too: a test run's pinned
    # configuration_ref not resolving is deterministic - the id/version
    # won't appear on retry, so autoretry would just burn 3 attempts for
    # the same failure.
    is_final_attempt = self.request.retries >= _ALERT_REVIEW_MAX_RETRIES
    return AlertReviewWorkflowRunner().run(
        UUID(workflow_execution_id), is_final_attempt=is_final_attempt
    )


@app.task(
    bind=True,
    name="workflows.alert_review.escalate_to_analyst",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def escalate_alert_to_analyst(
    self,
    alert_id: str,
    event_id: str,
    session_id: str | None,
    reason: str,
) -> dict:
    use_case = EscalateAlertToAnalystUseCase(
        aric_alert_port=MockAricAlertAdapter(),
        monitoring=get_monitoring(),
    )
    use_case.execute(
        EscalateAlertToAnalystInput(
            alert_id=UUID(alert_id),
            event_id=event_id,
            session_id=session_id,
            reason=reason,
        )
    )
    return {"status": "ok", "alert_id": alert_id}


@app.task(
    bind=True,
    name="workflows.alert_review.document_analyst_decision",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def document_analyst_decision(
    self,
    alert_id: str,
    workflow_execution_id: str,
    steps: dict[str, dict[str, Any]],
) -> dict:
    use_case = DocumentAnalystDecisionUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        model=genai_config.REPORT_LLM_MODEL,
        object_storage_port=get_object_storage(),
    )
    output = use_case.execute(
        DocumentAnalystDecisionInput(
            alert_id=UUID(alert_id),
            workflow_execution_id=UUID(workflow_execution_id),
            steps=steps,
        )
    )
    return {
        "status": "ok",
        "alert_id": alert_id,
        "object_storage_uri": output.object_storage_ref.uri,
    }


@app.task(
    bind=True,
    name="workflows.alert_review.execute_alert_action",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def execute_alert_action(self, action: str, alert_id: str) -> dict:
    use_case = ExecuteAlertActionUseCase(
        alert_action_port=MockAlertChannelActionAdapter(),
        monitoring=get_monitoring(),
    )
    output = use_case.execute(
        ExecuteAlertActionInput(action=action, alert_id=UUID(alert_id))
    )
    return {
        "status": "ok",
        "alert_id": alert_id,
        "action": output.action,
        "detail": output.detail,
    }


@app.task(
    bind=True,
    name="datasets.analyze",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def analyze_dataset_task(self, dataset_name: str) -> dict:
    use_case = AnalyzeDatasetUseCase(
        dataset_repository=MinioCsvDatasetRepository(get_dataset_object_storage()),
        sample_repository=DynamoDatasetSampleRepository(),
        summary_repository=DynamoDatasetSummaryRepository(),
    )
    use_case.execute(dataset_name)
    return {"status": "ok", "dataset_name": dataset_name}


# No autoretry (unlike analyze_dataset_task above): a training run is
# expensive (minutes of XGBoost fitting) and its progress is already
# persisted incrementally in the AsyncOperationRecord - a transient failure
# should surface as FAILED for the user to re-trigger explicitly via
# "Entrenar" again, not silently re-run a costly job in the background.
@app.task(name="models.train")
def train_model_task(model_id: str, async_operation_id: str) -> dict:
    from src.infrastructure.persistence.database.dynamodb.repositories.model_repository import (
        DynamoModelRepository,
    )
    from src.infrastructure.persistence.object_storage.minio import (
        get_model_object_storage,
    )
    from src.infrastructure.workflows.celery.model_training import (
        run_model_training,
    )

    return run_model_training(
        model_id,
        async_operation_id,
        model_repository=DynamoModelRepository(),
        async_operation_repository=DynamoAsyncOperationRepository(),
        dataset_repository=MinioCsvDatasetRepository(get_dataset_object_storage()),
        model_object_storage=get_model_object_storage(),
    )


@app.task(name="models.preview_features")
def preview_features_task(configuration: dict, rows: list[dict], target_field: str | None = None) -> dict:
    """Run an untrusted feature preview away from the API process."""
    from src.application.use_cases.models.feature_engineering import PreviewFeaturesUseCase

    return PreviewFeaturesUseCase().execute(configuration, rows, target_field)


# No autoretry (contrast with analyze_dataset_task above): a malformed
# workbook is a deterministic user-input error, not a transient one -
# retrying with backoff would only delay the FAILED result reaching the
# user, never turn it into a success. Result is read back via Celery's own
# result backend (AsyncResult), not a DynamoDB record - see
# analyst_capacity_import_port.py for why.
@app.task(name="analyst_capacity.parse_workbook")
def parse_analyst_capacity_workbook_task(content_b64: str) -> dict:
    # Lazy import: openpyxl is a worker-only dependency (see pyproject.
    # worker.toml) - tasks.py itself is also imported by the API process
    # (CeleryAnalystCapacityImportDispatcher imports this module just to
    # call .delay()), which never actually parses a workbook and doesn't
    # carry openpyxl in its own deps.
    from src.application.use_cases.analyst_capacity.workbook_parsing import (
        parse_analyst_capacity_workbook,
    )

    content = base64.b64decode(content_b64)
    profiles, day_overrides = parse_analyst_capacity_workbook(content)
    return {
        "profiles": [asdict(p) for p in profiles],
        "day_overrides": {str(day): profile_id for day, profile_id in day_overrides.items()},
    }
