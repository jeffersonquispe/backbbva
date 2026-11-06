"""LLM-judge verdicts (D6) for the alert detail and the /monitor KPIs.

Permission ``monitor`` (the KPIs already live there). The response carries the
judge's rationale and per-step notes, never the judge prompt or the raw
evidence it was given."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    GetAlertReasoningEvaluation,
    ListReasoningEvaluations,
    ReasoningEvaluationAlertNotFoundError,
    ReasoningEvaluationRangeError,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.reasoning_evaluation_factory import (
    get_get_alert_reasoning_evaluation_use_case,
    get_list_reasoning_evaluations_use_case,
)

router = APIRouter(tags=["reasoning-evaluations"])


class StepVerdictResponse(BaseModel):
    step: str
    hallucination: bool
    data_use_correct: bool
    note: str = ""


class ReasoningEvaluationResponse(BaseModel):
    alert_id: UUID
    status: str
    hallucination: bool | None
    data_use_correct: bool | None
    rationale: str
    judge_model: str
    prompt_version: str
    attempts: int
    input_tokens: int
    output_tokens: int
    evaluated_at: datetime
    steps: list[StepVerdictResponse]


class AlertReasoningEvaluationResponse(BaseModel):
    alert_id: UUID
    # evaluated | invalid | pending | not_sampled | not_applicable
    state: str
    evaluation: ReasoningEvaluationResponse | None


def _evaluation(record: AlertReasoningEvaluationRecord) -> ReasoningEvaluationResponse:
    return ReasoningEvaluationResponse(
        alert_id=record.alert_id,
        status=record.status.value,
        hallucination=record.hallucination,
        data_use_correct=record.data_use_correct,
        rationale=record.rationale,
        judge_model=record.judge_model,
        prompt_version=record.prompt_version,
        attempts=record.attempts,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        evaluated_at=record.evaluated_at,
        steps=[
            StepVerdictResponse(
                step=name,
                hallucination=bool(verdict.get("hallucination")),
                data_use_correct=bool(verdict.get("data_use_correct")),
                note=str(verdict.get("note") or ""),
            )
            for name, verdict in record.step_verdicts.items()
        ],
    )


@router.get(
    "/alerts/{alert_id}/reasoning-evaluation",
    response_model=AlertReasoningEvaluationResponse,
    dependencies=[Depends(require_permission("monitor"))],
)
def get_alert_reasoning_evaluation(
    alert_id: UUID,
    use_case: Annotated[
        GetAlertReasoningEvaluation,
        Depends(get_get_alert_reasoning_evaluation_use_case),
    ],
) -> AlertReasoningEvaluationResponse:
    """What the LLM-judge concluded about this alert, or why it has no verdict."""
    try:
        view = use_case.execute(alert_id)
    except ReasoningEvaluationAlertNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "ALERT_NOT_FOUND"}
        ) from error
    return AlertReasoningEvaluationResponse(
        alert_id=view.alert_id,
        state=view.state.value,
        evaluation=_evaluation(view.evaluation) if view.evaluation else None,
    )


@router.get(
    "/metrics/reasoning-evaluations",
    response_model=list[ReasoningEvaluationResponse],
    dependencies=[Depends(require_permission("monitor"))],
)
def list_reasoning_evaluations(
    use_case: Annotated[
        ListReasoningEvaluations, Depends(get_list_reasoning_evaluations_use_case)
    ],
    from_day: Annotated[date, Query()],
    to_day: Annotated[date, Query()],
    hallucination: Annotated[bool | None, Query()] = None,
    data_use_correct: Annotated[bool | None, Query()] = None,
    status: Annotated[ReasoningEvaluationStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ReasoningEvaluationResponse]:
    """Judged alerts of a period (at most 31 days), newest first, filterable
    by verdict. Only verdicts stored with an evaluation day are listed."""
    try:
        records = use_case.execute(
            from_day=from_day,
            to_day=to_day,
            hallucination=hallucination,
            data_use_correct=data_use_correct,
            status=status,
            limit=limit,
        )
    except ReasoningEvaluationRangeError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "REASONING_EVALUATION_RANGE", "message": str(error)},
        ) from error
    return [_evaluation(record) for record in records]
