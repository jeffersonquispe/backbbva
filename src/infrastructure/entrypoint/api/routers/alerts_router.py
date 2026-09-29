from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
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
from src.domain.alerts.exceptions import AlertPayloadTooLargeError
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_curate_alert_to_dataset_use_case,
    get_start_alert_test_workflow_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CurateAlertToDatasetRequest,
    CurateAlertToDatasetResponse,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


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
