from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import UUID
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from src.application.dtos.alert_dtos import (
    CurateAlertToDatasetInput,
    StartAlertWorkflowInput,
)
from src.application.ports.alert_port import AlertOrigin
from src.application.use_cases.alerts.curate_alert_to_dataset import (
    CurateAlertToDatasetUseCase,
)
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.application.dtos.alert_history_dtos import (
    AlertHistoryItem,
    ListAlertHistoryInput,
)
from src.application.dtos.fraud_review_dtos import ReviewFraudLabelInput
from src.application.ports.fraud_label_review_port import (
    FraudLabelReview,
    FraudLabelReviewChannel,
)
from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.alerts.list_alert_history import (
    InvalidHistoryCursorError,
    ListAlertHistory,
)
from src.application.use_cases.fraud_review.get_fraud_label_review_import import (
    GetFraudLabelReviewImport,
)
from src.application.use_cases.fraud_review.list_fraud_label_reviews import (
    ListFraudLabelReviews,
)
from src.application.use_cases.fraud_review.review_fraud_label import ReviewFraudLabel
from src.application.use_cases.fraud_review.upload_fraud_label_review_import import (
    UploadFraudLabelReviewImport,
)
from src.domain.alerts.exceptions import (
    AlertNotFoundError,
    AlertPayloadTooLargeError,
    InvalidFraudLabelError,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.fraud_review_factory import (
    get_get_fraud_label_review_import_use_case,
    get_list_alert_history_use_case,
    get_list_fraud_label_reviews_use_case,
    get_review_fraud_label_use_case,
    get_upload_fraud_label_review_import_use_case,
)
from src.infrastructure.entrypoint.api.metrics_query_params import (
    MetricsQueryParams,
    metrics_query_params,
)
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_object_storage,
    get_alert_repository,
    get_curate_alert_to_dataset_use_case,
    get_start_alert_test_workflow_use_case,
)
from src.infrastructure.entrypoint.api.factories.alert_schema_factory import get_alert_schema_repository
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas import (
    AlertHistoryItemSchema,
    AlertHistoryPageResponse,
    CurateAlertToDatasetRequest,
    CurateAlertToDatasetResponse,
    FraudLabelReviewImportResponse,
    FraudLabelReviewSchema,
    FraudReviewRequest,
    FraudReviewResponse,
    UploadFraudLabelReviewImportResponse,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _sensitive_value(value: Any, strategy: str) -> str:
    text = str(value)
    if strategy == "anonymize":
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return "*" * max(len(text) - 4, 4) + text[-4:]


def _apply_raw_sensitivity(payload: Any, path: str, strategy: str) -> None:
    """Redact one schema location, taking the first item through a list.

    ARIC locations can contain arrays (the schema contract says the first
    element is the selected value). Mutate only the copied payload returned by
    this endpoint; the object-storage source remains unchanged.
    """
    current = payload
    parts = [part for part in path.split(".") if part]
    if not parts:
        return
    for part in parts[:-1]:
        if isinstance(current, list):
            current = current[0] if current else None
        if not isinstance(current, dict) or part not in current:
            return
        current = current[part]
    if isinstance(current, list):
        current = current[0] if current else None
    if isinstance(current, dict) and parts[-1] in current:
        current[parts[-1]] = _sensitive_value(current[parts[-1]], strategy)


@router.get("/{alert_id}/raw", dependencies=[Depends(require_permission("alert_schema"))])
def get_raw_alert(alert_id: UUID, user=Depends(get_current_user)):
    alert = get_alert_repository().get(alert_id)
    if alert is None or alert.raw_payload_ref is None:
        raise HTTPException(status_code=404, detail="Alert raw payload not found")
    storage = get_alert_object_storage()
    payload = json.loads(storage.get_bytes(alert.raw_payload_ref.key))
    schema = get_alert_schema_repository().get(alert.schema_version) if alert.schema_version is not None else None
    for field in schema.fields if schema else []:
        if (field.data_source.value != "aric" or not field.is_sensible
                or not field.sensitivity_strategy or not field.field_ds_loc):
            continue
        _apply_raw_sensitivity(payload, field.field_ds_loc, field.sensitivity_strategy)
    storage.put_text(
        f"alerts/{alert_id}/audit/raw-access/{uuid.uuid4()}.json",
        json.dumps({"alert_id": str(alert_id), "user_id": str(user.id), "accessed_at": datetime.now(timezone.utc).isoformat()}),
        "application/json",
    )
    return payload


class AlertTestRequest(BaseModel):
    event: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=120)
    # Who is sending the alert - decides whether it runs while the agent is
    # switched off (see AlertOrigin). test_run is set internally by batch
    # runs, never accepted here.
    origin: Literal["manual", "simulator", "production"] = "manual"


class AlertTestResponse(BaseModel):
    alert_id: UUID
    async_operation_id: UUID
    workflow_execution_id: UUID
    status: str


@router.post(
    "/test",
    response_model=AlertTestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_alert_test_workflow(
    request: AlertTestRequest,
    use_case: Annotated[
        StartAlertTestWorkflowUseCase,
        Depends(get_start_alert_test_workflow_use_case),
    ],
):
    try:
        return use_case.execute(
            StartAlertWorkflowInput(
                payload=request.event,
                created_by=request.created_by,
                origin=AlertOrigin(request.origin),
            )
        )
    except AlertPayloadTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/{alert_id}/curate-to-dataset",
    response_model=CurateAlertToDatasetResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def curate_alert_to_dataset(
    alert_id: UUID,
    request: CurateAlertToDatasetRequest,
    use_case: Annotated[
        CurateAlertToDatasetUseCase, Depends(get_curate_alert_to_dataset_use_case)
    ],
):
    try:
        return use_case.execute(
            CurateAlertToDatasetInput(
                alert_id=alert_id,
                dataset_name=request.dataset_name,
                justification=request.justification,
                configuration_id=request.configuration_id,
                version=request.version,
            )
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Fraud history (A3) + fraud_label review (C5) ----------------------------

# A review CSV is three short columns per row - 5MB is ~100k rows, above the
# use case's own MAX_ROWS.
MAX_FRAUD_REVIEW_UPLOAD_BYTES = 5 * 1024 * 1024


def _history_item(item: AlertHistoryItem) -> AlertHistoryItemSchema:
    alert, m = item.alert, item.metrics
    return AlertHistoryItemSchema(
        alert_id=alert.id,
        event_id=alert.event_id,
        event_type=alert.event_type,
        status=alert.status.value,
        customer_id=alert.customer_id,
        created_at=alert.created_at,
        updated_at=alert.updated_at,
        has_snapshot=item.has_snapshot,
        origin=m.origin,
        segment=m.segment,
        channel=m.channel,
        subchannel=m.subchannel,
        amount=m.amount,
        amount_tier=m.amount_tier,
        schema_version=m.schema_version,
        configuration_id=m.configuration_id,
        resolution_method=m.resolution_method.value if m.resolution_method else None,
        mark=m.mark.value,
        fraud_label=m.fraud_label.value,
        marked_at=m.marked_at,
        fraud_reviewed_at=m.fraud_reviewed_at,
        fraud_review_count=m.fraud_review_count,
        resolution_time_seconds=m.resolution_time_seconds,
    )


def _review_schema(review: FraudLabelReview) -> FraudLabelReviewSchema:
    return FraudLabelReviewSchema(
        id=review.id,
        alert_id=review.alert_id,
        from_label=review.from_label.value,
        to_label=review.to_label.value,
        reviewed_by=review.reviewed_by,
        reviewed_at=review.reviewed_at,
        channel=review.channel.value,
        note=review.note,
    )


@router.get(
    "/history",
    response_model=AlertHistoryPageResponse,
    dependencies=[Depends(require_permission("fraud_history"))],
)
def list_alert_history(
    params: Annotated[MetricsQueryParams, Depends(metrics_query_params)],
    use_case: Annotated[ListAlertHistory, Depends(get_list_alert_history_use_case)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
):
    """Alerts newest first, paged by arrival day (CreatedDayIdx, no Scan).
    Follow next_cursor until null - a page can be short (even empty) with a
    cursor when the filters are very selective."""
    try:
        output = use_case.execute(
            ListAlertHistoryInput(
                from_=params.from_,
                to=params.to,
                filters=params.filters,
                limit=limit,
                cursor=cursor,
            )
        )
    except InvalidHistoryCursorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AlertHistoryPageResponse(
        items=[_history_item(item) for item in output.items],
        next_cursor=output.next_cursor,
    )


@router.post(
    "/fraud-review-imports",
    response_model=UploadFraudLabelReviewImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_fraud_label_review_import(
    user: Annotated[LocalUser, Depends(require_permission("fraud_review"))],
    use_case: Annotated[
        UploadFraudLabelReviewImport,
        Depends(get_upload_fraud_label_review_import_use_case),
    ],
    file: UploadFile,
):
    """Bulk review CSV (alert_id,fraud_label,note). Processed by the worker;
    poll GET /alerts/fraud-review-imports/{task_id} for the per-row report."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")
    content = await file.read()
    if len(content) > MAX_FRAUD_REVIEW_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 5MB)")
    task_id = use_case.execute(content, reviewed_by=user.email)
    return UploadFraudLabelReviewImportResponse(task_id=task_id, status="PENDING")


@router.get(
    "/fraud-review-imports/{task_id}",
    response_model=FraudLabelReviewImportResponse,
    dependencies=[Depends(require_permission("fraud_review"))],
)
def get_fraud_label_review_import(
    task_id: str,
    use_case: Annotated[
        GetFraudLabelReviewImport, Depends(get_get_fraud_label_review_import_use_case)
    ],
):
    result = use_case.execute(task_id)
    return FraudLabelReviewImportResponse(
        task_id=task_id,
        status=result.status.value,
        total=result.total,
        applied=result.applied,
        failed=result.failed,
        rows=[asdict(row) for row in result.rows],
        error=result.error,
    )


@router.post(
    "/{alert_id}/fraud-review",
    response_model=FraudReviewResponse,
)
def review_fraud_label(
    alert_id: UUID,
    request: FraudReviewRequest,
    user: Annotated[LocalUser, Depends(require_permission("fraud_review"))],
    use_case: Annotated[ReviewFraudLabel, Depends(get_review_fraud_label_use_case)],
):
    """The fraud team sets the alert's real outcome. Same value = a
    confirmation: still recorded and fills fraud_reviewed_at."""
    try:
        output = use_case.execute(
            ReviewFraudLabelInput(
                alert_id=alert_id,
                fraud_label=request.fraud_label,
                reviewed_by=user.email,
                channel=FraudLabelReviewChannel.UI,
                note=request.note,
            )
        )
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidFraudLabelError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    snapshot = output.snapshot
    return FraudReviewResponse(
        review=_review_schema(output.review),
        mark=snapshot.mark.value,
        fraud_label=snapshot.fraud_label.value,
        marked_at=snapshot.marked_at,
        fraud_reviewed_at=snapshot.fraud_reviewed_at,
        fraud_review_count=snapshot.fraud_review_count,
    )


@router.get(
    "/{alert_id}/fraud-reviews",
    response_model=list[FraudLabelReviewSchema],
    dependencies=[Depends(require_permission("fraud_history"))],
)
def list_fraud_label_reviews(
    alert_id: UUID,
    use_case: Annotated[
        ListFraudLabelReviews, Depends(get_list_fraud_label_reviews_use_case)
    ],
):
    """The alert's fraud_label audit trail, oldest first."""
    return [_review_schema(review) for review in use_case.execute(alert_id)]
