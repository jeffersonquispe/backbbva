"""LLM-judge verdict reads (D6) wiring for the API."""

from __future__ import annotations

from functools import lru_cache

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRepository,
)
from src.application.ports.reasoning_evaluation_job_port import (
    ReasoningEvaluationJobRepository,
)
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    GetAlertReasoningEvaluation,
    ListReasoningEvaluations,
)
from src.application.use_cases.metrics.request_reasoning_evaluation import (
    RequestReasoningEvaluation,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_operational_settings_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_reasoning_evaluation_repository import (
    DynamoAlertReasoningEvaluationRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.reasoning_evaluation_job_repository import (
    DynamoReasoningEvaluationJobRepository,
)
from src.infrastructure.queues.celery.reasoning_evaluation_dispatcher import (
    CeleryReasoningEvaluationJobDispatcher,
)


@lru_cache(maxsize=1)
def get_alert_reasoning_evaluation_repository() -> AlertReasoningEvaluationRepository:
    return DynamoAlertReasoningEvaluationRepository()


def get_get_alert_reasoning_evaluation_use_case() -> GetAlertReasoningEvaluation:
    return GetAlertReasoningEvaluation(
        get_alert_reasoning_evaluation_repository(),
        get_alert_repository(),
        get_reasoning_evaluation_job_repository(),
    )


@lru_cache(maxsize=1)
def get_reasoning_evaluation_job_repository() -> ReasoningEvaluationJobRepository:
    return DynamoReasoningEvaluationJobRepository()


def get_request_reasoning_evaluation_use_case() -> RequestReasoningEvaluation:
    """On-demand evaluation: the API only opens the job and queues it; the
    evaluator's worker does the judging."""
    return RequestReasoningEvaluation(
        jobs=get_reasoning_evaluation_job_repository(),
        alerts=get_alert_repository(),
        settings=get_operational_settings_repository(),
        dispatcher=CeleryReasoningEvaluationJobDispatcher(),
        clock=get_clock(),
    )


def get_list_reasoning_evaluations_use_case() -> ListReasoningEvaluations:
    return ListReasoningEvaluations(get_alert_reasoning_evaluation_repository())
