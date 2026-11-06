"""LLM-judge verdict reads (D6) wiring for the API."""

from __future__ import annotations

from functools import lru_cache

from src.application.ports.alert_reasoning_evaluation_port import (
    AlertReasoningEvaluationRepository,
)
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    GetAlertReasoningEvaluation,
    ListReasoningEvaluations,
)
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_operational_settings_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.alert_reasoning_evaluation_repository import (
    DynamoAlertReasoningEvaluationRepository,
)


@lru_cache(maxsize=1)
def get_alert_reasoning_evaluation_repository() -> AlertReasoningEvaluationRepository:
    return DynamoAlertReasoningEvaluationRepository()


def get_get_alert_reasoning_evaluation_use_case() -> GetAlertReasoningEvaluation:
    return GetAlertReasoningEvaluation(
        get_alert_reasoning_evaluation_repository(),
        get_alert_repository(),
        get_operational_settings_repository(),
    )


def get_list_reasoning_evaluations_use_case() -> ListReasoningEvaluations:
    return ListReasoningEvaluations(get_alert_reasoning_evaluation_repository())
