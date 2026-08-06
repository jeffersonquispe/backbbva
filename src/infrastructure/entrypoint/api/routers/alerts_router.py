from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from src.application.dtos.alert_dtos import StartAlertWorkflowInput
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_start_alert_test_workflow_use_case,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertTestRequest(BaseModel):
    event: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=120)


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
    return use_case.execute(
        StartAlertWorkflowInput(
            payload=request.event,
            created_by=request.created_by,
        )
    )
