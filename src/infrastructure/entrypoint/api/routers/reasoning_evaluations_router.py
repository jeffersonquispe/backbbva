"""LLM-judge verdicts (D6) for the alert detail and the /monitor KPIs.

Permission ``monitor`` (the KPIs already live there). The response carries the
judge's rationale and per-step notes, never the judge prompt or the raw
evidence it was given."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRecord,
    ReasoningEvaluationStatus,
)
from src.application.ports.local_auth_port import LocalUser
from src.application.ports.reasoning_evaluation_job_port import ReasoningEvaluationJob
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    GetAlertReasoningEvaluation,
    ListReasoningEvaluations,
    ReasoningEvaluationAlertNotFoundError,
    ReasoningEvaluationRangeError,
)
from src.application.use_cases.metrics.reasoning_criteria import (
    ALERT_CRITERIA,
    DEFAULT_CRITERIA,
)
from src.application.use_cases.metrics.request_reasoning_evaluation import (
    ReasoningEvaluationNotReadyError,
    RequestOutcome,
    RequestReasoningEvaluation,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.reasoning_evaluation_factory import (
    get_get_alert_reasoning_evaluation_use_case,
    get_list_reasoning_evaluations_use_case,
    get_request_reasoning_evaluation_use_case,
)

router = APIRouter(tags=["reasoning-evaluations"])


class StepVerdictResponse(BaseModel):
    step: str
    hallucination: bool
    data_use_correct: bool
    note: str = ""


class CriterionVerdictResponse(BaseModel):
    key: str
    label: str
    # None = the judge could not decide it (e.g. no model output to compare).
    passed: bool | None
    note: str = ""


class CriterionResponse(BaseModel):
    key: str
    label: str
    question: str
    scope: str
    optional: bool
    counts_in_rollups: bool


class JobResponse(BaseModel):
    status: str
    requested_by: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempts: int
    error_code: str | None
    # How long it waited for the worker, how long the judge took, and the whole
    # way from queued to verdict (all in milliseconds, None until known).
    wait_ms: int | None
    run_ms: int
    total_ms: int | None


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
    duration_ms: int
    steps: list[StepVerdictResponse]
    criteria: list[CriterionVerdictResponse]


class AlertReasoningEvaluationResponse(BaseModel):
    alert_id: UUID
    # evaluated | invalid | queued | running | failed | not_sampled | not_applicable
    state: str
    evaluation: ReasoningEvaluationResponse | None
    job: JobResponse | None = None


def _job(job: ReasoningEvaluationJob | None) -> JobResponse | None:
    if job is None:
        return None
    return JobResponse(
        status=job.status.value,
        requested_by=job.requested_by,
        queued_at=job.queued_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        attempts=job.attempts,
        error_code=job.error_code,
        wait_ms=job.wait_ms,
        run_ms=job.run_ms,
        total_ms=job.total_ms,
    )


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
        duration_ms=record.duration_ms,
        criteria=[
            CriterionVerdictResponse(
                key=criterion.key,
                label=criterion.label,
                passed=record.criteria_verdicts[criterion.key].get("passed"),  # type: ignore[arg-type]
                note=str(record.criteria_verdicts[criterion.key].get("note") or ""),
            )
            for criterion in ALERT_CRITERIA
            if criterion.key in record.criteria_verdicts
        ],
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
        job=_job(view.job),
    )


@router.post(
    "/alerts/{alert_id}/reasoning-evaluation",
    response_model=AlertReasoningEvaluationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_alert_reasoning_evaluation(
    alert_id: UUID,
    _: Annotated[LocalUser, Depends(require_permission("configuration"))],
    use_case: Annotated[
        RequestReasoningEvaluation, Depends(get_request_reasoning_evaluation_use_case)
    ],
) -> AlertReasoningEvaluationResponse:
    """Evaluate this alert now, whatever the sample rate. It only opens the job
    and queues it for the evaluator's worker (202): the answer comes later through
    ``GET``. Asking twice returns the existing job; a failed or invalid one is
    queued again. Costs an LLM call, hence the ``configuration`` permission."""
    try:
        output = use_case.execute(alert_id, forced=True)
    except ReasoningEvaluationAlertNotFoundError as error:
        raise HTTPException(
            status_code=404, detail={"code": "ALERT_NOT_FOUND"}
        ) from error
    except ReasoningEvaluationNotReadyError as error:
        raise HTTPException(
            status_code=409, detail={"code": "ALERT_NOT_FINISHED"}
        ) from error
    if output.outcome == RequestOutcome.NOT_APPLICABLE:
        raise HTTPException(status_code=409, detail={"code": "ALERT_NOT_JUDGEABLE"})
    job = output.job
    state = (
        {
            "queued": "queued",
            "running": "running",
            "failed": "failed",
            "invalid": "invalid",
            "evaluated": "evaluated",
        }[job.status.value]
        if job
        else "queued"
    )
    return AlertReasoningEvaluationResponse(
        alert_id=alert_id, state=state, evaluation=None, job=_job(job)
    )


@router.get(
    "/metrics/reasoning-evaluation-criteria",
    response_model=list[CriterionResponse],
    dependencies=[Depends(require_permission("monitor"))],
)
def list_reasoning_evaluation_criteria() -> list[CriterionResponse]:
    """The criteria the judge applies by default, with the question it asks."""
    return [
        CriterionResponse(
            key=c.key,
            label=c.label,
            question=c.question,
            scope=c.scope,
            optional=c.optional,
            counts_in_rollups=c.counts_in_rollups,
        )
        for c in DEFAULT_CRITERIA
    ]


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
