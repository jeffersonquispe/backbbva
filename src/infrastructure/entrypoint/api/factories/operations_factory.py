from __future__ import annotations

from functools import lru_cache

from src.application.ports.alert_action_dispatcher_port import AlertActionDispatcher
from src.application.use_cases.analyst_queue.get_alert_detail import (
    GetAlertDetailUseCase,
)
from src.application.use_cases.analyst_queue.list_analyst_queue import (
    ListAnalystQueueUseCase,
)
from src.application.use_cases.analyst_queue.release_escalated_alert import (
    ReleaseEscalatedAlertUseCase,
)
from src.application.use_cases.analyst_queue.resolve_escalated_alert import (
    ResolveEscalatedAlertUseCase,
)
from src.application.use_cases.analyst_queue.take_escalated_alert import (
    TakeEscalatedAlertUseCase,
)
from src.application.use_cases.operations.complete_voicebot_call import (
    CompleteVoicebotCallUseCase,
)
from src.application.use_cases.operations.live_operations_capacity import (
    LiveOperationsCapacity,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
    get_workflow_execution_repository,
)
from src.infrastructure.entrypoint.api.factories.metrics_factory import (
    get_record_alert_metrics_event_use_case,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_operational_settings_repository,
)
from src.infrastructure.entrypoint.api.factories.test_run_factory import (
    get_workflow_step_execution_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.operations_capacity_repository import (
    DynamoOperationsCapacityRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.resource_reservation_repository import (
    DynamoResourceReservationRepository,
)


@lru_cache
def get_resource_reservation_repository() -> DynamoResourceReservationRepository:
    return DynamoResourceReservationRepository()


@lru_cache
def get_live_operations_capacity() -> LiveOperationsCapacity:
    return LiveOperationsCapacity(
        settings_repository=get_operational_settings_repository(),
        reservation_repository=get_resource_reservation_repository(),
        static_capacity=DynamoOperationsCapacityRepository(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
    )


@lru_cache
def get_alert_action_dispatcher() -> AlertActionDispatcher:
    # Lazy: pulls in the Celery app only when an analyst actually resolves.
    from src.infrastructure.queues.celery.alert_action_dispatcher import (
        CeleryAlertActionDispatcher,
    )

    return CeleryAlertActionDispatcher()


def get_list_analyst_queue_use_case() -> ListAnalystQueueUseCase:
    return ListAnalystQueueUseCase(
        get_alert_repository(), get_resource_reservation_repository()
    )


def get_alert_detail_use_case() -> GetAlertDetailUseCase:
    return GetAlertDetailUseCase(
        get_alert_repository(),
        get_resource_reservation_repository(),
        get_workflow_execution_repository(),
        get_workflow_step_execution_repository(),
    )


def get_take_escalated_alert_use_case() -> TakeEscalatedAlertUseCase:
    return TakeEscalatedAlertUseCase(
        get_alert_repository(),
        get_resource_reservation_repository(),
        get_live_operations_capacity(),
    )


def get_resolve_escalated_alert_use_case() -> ResolveEscalatedAlertUseCase:
    return ResolveEscalatedAlertUseCase(
        get_alert_repository(),
        get_resource_reservation_repository(),
        get_alert_action_dispatcher(),
        metrics_recorder=get_record_alert_metrics_event_use_case(),
    )


def get_release_escalated_alert_use_case() -> ReleaseEscalatedAlertUseCase:
    return ReleaseEscalatedAlertUseCase(get_resource_reservation_repository())


def get_complete_voicebot_call_use_case() -> CompleteVoicebotCallUseCase:
    return CompleteVoicebotCallUseCase(
        get_resource_reservation_repository(),
        metrics_recorder=get_record_alert_metrics_event_use_case(),
    )
