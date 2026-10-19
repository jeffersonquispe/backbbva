from __future__ import annotations

import base64
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from src.application.dtos.async_reconciliation_dtos import (
    ReconcileAsyncOperationsInput,
)
from src.application.dtos.dataset_dtos import FraudMarkingAnalysisInput
from src.application.dtos.document_analyst_decision_dtos import (
    DocumentAnalystDecisionInput,
)
from src.application.dtos.escalate_alert_dtos import (
    EscalateAlertToAnalystInput,
)
from src.application.dtos.execute_alert_action_dtos import (
    ExecuteAlertActionInput,
)
from src.application.dtos.reasoning_evaluation_dtos import (
    EvaluateAlertReasoningInput,
)
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.backup_catalog_port import BackupStatus
from src.application.use_cases.async_operations.create_async_operation import (
    GENERIC_OPERATION_TYPES,
)
from src.domain.alerts.exceptions import AdversarialFeedbackLimitExceededError
from src.domain.configurations.exceptions import ConfigurationNotFoundError
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.worker.celery.celery_app import app
from src.infrastructure.workflows.celery.factories import (
    get_async_operation_repository,
    get_evaluate_alert_reasoning_use_case,
    get_metrics_rollup_maintenance_repository,
    get_model_repository,
    get_model_storage,
    get_operational_settings_repository,
)
from src.infrastructure.workflows.celery.task_factories import (
    get_analyze_dataset_use_case,
    get_analyze_fraud_marking_use_case,
    get_apply_object_storage_retention_use_case,
    get_backup_catalog_repository,
    get_cleanup_test_runs_use_case,
    get_dataset_repository,
    get_delete_dataset_use_case,
    get_document_analyst_decision_use_case,
    get_escalate_alert_to_analyst_use_case,
    get_execute_alert_action_use_case,
    get_object_storage_retention_rules,
    get_preview_features_use_case,
    get_reconcile_async_operations_use_case,
    get_run_alert_review_workflow_use_case,
)


@app.task(name="queue.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "backend": "celery"}


@app.task(name="backups.create")
def create_backup(backup_id: str) -> dict[str, str | int]:
    import importlib.util
    from pathlib import Path

    backup_script = Path(__file__).resolve().parents[5] / "scripts" / "db_backup.py"
    spec = importlib.util.spec_from_file_location("aria_db_backup", backup_script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load backup script: {backup_script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    backup = module.backup

    repository = get_backup_catalog_repository()
    record = repository.get(backup_id)
    if record is None:
        return {"status": "not_found", "backup_id": backup_id}
    running = replace(record, status=BackupStatus.RUNNING, updated_at=datetime.now(UTC))
    repository.update(running)
    try:
        backup(Path(record.directory), skip_object_storage=False)
        manifest = json.loads(
            (Path(record.directory) / "manifest.json").read_text(encoding="utf-8")
        )
        succeeded = replace(
            running,
            status=BackupStatus.SUCCEEDED,
            updated_at=datetime.now(UTC),
            dynamodb_items=sum(
                table["items"] for table in manifest["dynamodb"].values()
            ),
            opensearch_documents=(manifest.get("opensearch") or {}).get("documents", 0),
            object_storage_objects=len(
                (manifest.get("object_storage") or {}).get("objects", [])
            ),
        )
        repository.update(succeeded)
        return {"status": succeeded.status.value, "backup_id": backup_id}
    except Exception as exc:
        repository.update(
            replace(
                running,
                status=BackupStatus.FAILED,
                updated_at=datetime.now(UTC),
                error=str(exc),
            )
        )
        raise


@app.task(name="async_operations.run")
def run_async_operation(operation_id: str) -> dict[str, str]:
    repository = get_async_operation_repository()
    operation_uuid = UUID(operation_id)

    operation = repository.get(operation_uuid)
    if operation is None:
        return {"status": "not_found", "operation_id": operation_id}

    # No generic handlers are registered yet (GENERIC_OPERATION_TYPES is
    # empty): never report SUCCEEDED for work that wasn't done. Real
    # operation types dispatch their own tasks; see the use case's note.
    if operation.operation_type not in GENERIC_OPERATION_TYPES:
        error = f"Unsupported async operation type: {operation.operation_type}"
        repository.update(
            operation_uuid, status=AsyncOperationStatus.FAILED, error=error
        )
        return {"status": "failed", "operation_id": operation_id, "error": error}

    raise NotImplementedError(
        f"No handler registered for async operation type {operation.operation_type}"
    )


@app.task(name="async_operations.reconcile")
def reconcile_async_operations(limit: int = 100) -> dict:
    output = get_reconcile_async_operations_use_case().execute(
        ReconcileAsyncOperationsInput(limit=limit)
    )
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


@app.task(name="test_runs.cleanup")
def cleanup_test_runs() -> dict[str, int]:
    settings = get_operational_settings_repository().get()
    output = get_cleanup_test_runs_use_case().execute(
        settings.max_stored_test_runs, settings.test_cleanup_policy
    )
    return {
        "deleted_test_runs": output.deleted_test_runs,
        "deleted_cases": output.deleted_cases,
        "deferred_active_runs": output.deferred_active_runs,
    }


@app.task(name="object_storage.retention")
def apply_object_storage_retention() -> dict[str, Any]:
    if not genai_config.OBJECT_STORAGE_RETENTION_ENABLED:
        return {"enabled": False}
    output = get_apply_object_storage_retention_use_case().execute(
        get_object_storage_retention_rules(),
        dry_run=genai_config.OBJECT_STORAGE_RETENTION_DRY_RUN,
    )
    return {
        "enabled": True,
        "dry_run": output.dry_run,
        "deleted": output.deleted,
        "rules": [
            {
                "store": r.rule.store,
                "prefix": r.rule.prefix,
                "max_age_days": r.rule.max_age_days,
                "matched": r.matched,
                "deleted": r.deleted,
                "failed": r.failed,
                "bytes_matched": r.bytes_matched,
            }
            for r in output.results
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
    output = get_run_alert_review_workflow_use_case().execute(
        UUID(workflow_execution_id), is_final_attempt=is_final_attempt
    )
    return asdict(output)


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
    get_escalate_alert_to_analyst_use_case().execute(
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
    output = get_document_analyst_decision_use_case().execute(
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


# D6 LLM-judge for a sampled, finished alert (dispatched by the alert
# review runner). Safe to autoretry: EvaluateAlertReasoning reuses a stored
# verdict and counts it at most once (apply_once marker per alert).
@app.task(
    bind=True,
    name="metrics.evaluate_alert_reasoning",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def evaluate_alert_reasoning(self, alert_id: str, workflow_execution_id: str) -> dict:
    output = get_evaluate_alert_reasoning_use_case().execute(
        EvaluateAlertReasoningInput(
            alert_id=UUID(alert_id),
            workflow_execution_id=UUID(workflow_execution_id),
        )
    )
    evaluation = output.evaluation
    return {
        "status": evaluation.status.value if evaluation is not None else "skipped",
        "alert_id": alert_id,
        "counted": output.counted,
    }


@app.task(
    bind=True,
    name="workflows.alert_review.execute_alert_action",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def execute_alert_action(
    self, action: str, alert_id: str, content: str | None = None
) -> dict:
    output = get_execute_alert_action_use_case().execute(
        ExecuteAlertActionInput(action=action, alert_id=UUID(alert_id), content=content)
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
def analyze_dataset_task(
    self, dataset_name: str, operation_id: str | None = None
) -> dict:
    operation_repository = get_async_operation_repository()
    if operation_id:
        operation_repository.update(
            UUID(operation_id),
            status=AsyncOperationStatus.RUNNING,
            result={"stage": "starting", "progress_pct": 1},
        )
    try:
        get_analyze_dataset_use_case().execute(
            dataset_name,
            progress=(
                lambda result: operation_repository.update(
                    UUID(operation_id), result=result
                )
                if operation_id
                else None
            ),
        )
    except Exception as exc:
        if operation_id:
            operation_repository.update(
                UUID(operation_id), status=AsyncOperationStatus.FAILED, error=str(exc)
            )
        raise
    if operation_id:
        operation_repository.update(
            UUID(operation_id),
            status=AsyncOperationStatus.SUCCEEDED,
            result={"stage": "done", "progress_pct": 100, "dataset_name": dataset_name},
        )
    return {"status": "ok", "dataset_name": dataset_name}


@app.task(name="datasets.delete")
def delete_dataset_task(dataset_name: str, operation_id: str) -> dict:
    """Remove a dataset outside the API process and report every stage."""
    operations = get_async_operation_repository()
    operation_uuid = UUID(operation_id)
    operations.update(
        operation_uuid,
        status=AsyncOperationStatus.RUNNING,
        result={"stage": "removing_dataset", "progress_pct": 5},
    )
    try:
        # The use case's repository calls are idempotent; a retry or a delete
        # requested twice is safe.
        get_delete_dataset_use_case().execute(dataset_name)
    except Exception as exc:
        operations.update(
            operation_uuid, status=AsyncOperationStatus.FAILED, error=str(exc)
        )
        raise
    operations.update(
        operation_uuid,
        status=AsyncOperationStatus.SUCCEEDED,
        result={"stage": "done", "progress_pct": 100, "dataset_name": dataset_name},
    )
    return {"status": "ok", "dataset_name": dataset_name}


@app.task(name="datasets.analyze_fraud_marking")
def analyze_fraud_marking_task(
    dataset_name: str,
    first_mark_field: str,
    second_mark_field: str,
    first_mark_time_field: str,
    second_mark_time_field: str,
    positive_values: list[str],
    operation_id: str,
) -> dict:
    """Compute a marking analysis outside the API request lifecycle."""
    operations = get_async_operation_repository()
    operation_uuid = UUID(operation_id)
    operations.update(
        operation_uuid,
        status=AsyncOperationStatus.RUNNING,
        result={"stage": "analyzing", "progress_pct": 1},
    )
    try:
        output = get_analyze_fraud_marking_use_case().execute(
            FraudMarkingAnalysisInput(
                dataset_name=dataset_name,
                first_mark_field=first_mark_field,
                second_mark_field=second_mark_field,
                first_mark_time_field=first_mark_time_field,
                second_mark_time_field=second_mark_time_field,
                positive_values=positive_values,
            ),
            progress=lambda result: operations.update(operation_uuid, result=result),
        )
    except Exception as exc:
        operations.update(
            operation_uuid, status=AsyncOperationStatus.FAILED, error=str(exc)
        )
        raise
    result = asdict(output)
    operations.update(
        operation_uuid,
        status=AsyncOperationStatus.SUCCEEDED,
        result={"stage": "done", "progress_pct": 100, "analysis": result},
    )
    return result


# No autoretry (unlike analyze_dataset_task above): a training run is
# expensive (minutes of XGBoost fitting) and its progress is already
# persisted incrementally in the AsyncOperationRecord - a transient failure
# should surface as FAILED for the user to re-trigger explicitly via
# "Entrenar" again, not silently re-run a costly job in the background.
@app.task(name="models.train")
def train_model_task(model_id: str, async_operation_id: str) -> dict:
    from src.infrastructure.workflows.celery.model_training import (
        run_model_training,
    )

    return run_model_training(
        model_id,
        async_operation_id,
        model_repository=get_model_repository(),
        async_operation_repository=get_async_operation_repository(),
        dataset_repository=get_dataset_repository(),
        model_object_storage=get_model_storage(),
    )


@app.task(name="models.preview_features")
def preview_features_task(
    configuration: dict, rows: list[dict], target_field: str | None = None
) -> dict:
    """Run an untrusted feature preview away from the API process."""
    return get_preview_features_use_case().execute(configuration, rows, target_field)


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
    from src.infrastructure.entrypoint.worker.analyst_capacity_workbook import (
        parse_analyst_capacity_workbook,
    )

    content = base64.b64decode(content_b64)
    profiles, day_overrides = parse_analyst_capacity_workbook(content)
    return {
        "profiles": [asdict(p) for p in profiles],
        "day_overrides": {
            str(day): profile_id for day, profile_id in day_overrides.items()
        },
    }


# Bulk fraud_label review CSV (C5). No autoretry: a bad row is reported in
# the result and never aborts the batch, and every applied row is already
# idempotence-safe through RecordAlertMetricsEvent's snapshot_version guard
# - but a retry would append duplicate audit rows. The per-row report is
# read back via Celery's result backend (fraud_label_review_import_port.py).
@app.task(name="fraud_review.import_csv")
def import_fraud_label_reviews_task(content_b64: str, reviewed_by: str) -> dict:
    # Lazy import: keeps the worker-side factories out of the API process,
    # which imports this module only to call .delay().
    from src.infrastructure.workflows.celery.factories import (
        get_import_fraud_label_reviews_use_case,
    )

    result = get_import_fraud_label_reviews_use_case().execute(
        base64.b64decode(content_b64), reviewed_by
    )
    return {
        "status": result.status.value,
        "total": result.total,
        "applied": result.applied,
        "failed": result.failed,
        "error": result.error,
        "rows": [
            {
                "row": row.row,
                "alert_id": row.alert_id,
                "fraud_label": row.fraud_label,
                "status": row.status.value,
                "error": row.error,
            }
            for row in result.rows
        ],
    }


@app.task(name="metrics.reconcile_alert_rollups")
def reconcile_alert_rollups() -> dict:
    # Worker-only factory, imported here so the module import stays light.
    from src.infrastructure.workflows.celery.factories import (
        get_reconcile_alert_rollups_use_case,
    )

    output = get_reconcile_alert_rollups_use_case().execute()
    return {
        "drift": output.drift,
        "drift_by_level": output.drift_by_level,
        "corrected": output.corrected,
        "skipped_concurrent": output.skipped_concurrent,
        "rows_checked": output.rows_checked,
        "days_checked": output.days_checked,
        "months_checked": output.months_checked,
        "snapshots_backfilled": output.snapshots_backfilled,
    }


@app.task(name="metrics.cleanup_expired_rollups")
def cleanup_expired_metric_rollups() -> dict[str, int]:
    """Prune expired day rollups and idempotency markers in bounded batches."""
    deleted = get_metrics_rollup_maintenance_repository().delete_expired(
        int(datetime.now(UTC).timestamp())
    )
    return {"deleted": deleted}


# T3/T5: one sample of the operational gauges per Beat tick (60 s, see
# celery_app.periodic_schedule). No retry: the next tick is the retry.
@app.task(name="metrics.record_operational_state")
def record_operational_state() -> dict:
    from src.infrastructure.workflows.celery.factories import (
        get_record_operational_state_use_case,
    )

    snapshot = get_record_operational_state_use_case().execute()
    return asdict(snapshot)


@app.task(name="alert_schema.analyze_presence")
def analyze_alert_schema_presence() -> dict | None:
    from src.infrastructure.workflows.celery.factories import (
        get_analyze_alert_schema_presence_use_case,
    )

    report = get_analyze_alert_schema_presence_use_case().execute()
    if report is None:
        return None
    return _json_safe(asdict(report))


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
