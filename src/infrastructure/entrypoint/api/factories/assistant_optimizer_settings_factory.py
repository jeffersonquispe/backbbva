from __future__ import annotations

from functools import lru_cache

from src.application.use_cases.assistant_optimizer_settings import (
    GetAssistantOptimizerSettingsUseCase,
    ListAssistantOptimizerSettingsChangesUseCase,
    UpdateAssistantOptimizerSettingsUseCase,
)
from src.application.use_cases.async_operations.create_async_operation import (
    CreateAsyncOperationUseCase,
)
from src.application.use_cases.datasets.preview_mature_sample import (
    PreviewMatureSampleUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
)
from src.infrastructure.entrypoint.api.factories.alert_schema_factory import (
    get_alert_schema_repository,
)
from src.infrastructure.entrypoint.api.factories.async_operation_factory import (
    get_async_operation_repository,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_operational_settings_repository,
)
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.assistant_optimizer_settings_repository import (
    DynamoAssistantOptimizerSettingsRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.mature_sample_repository import (
    DynamoDatasetSamplerStateRepository,
)
from src.infrastructure.queues.celery.mature_sample_executor import (
    CeleryMatureSampleExecutor,
)


@lru_cache
def get_assistant_optimizer_settings_repository() -> DynamoAssistantOptimizerSettingsRepository:
    return DynamoAssistantOptimizerSettingsRepository()


def get_get_assistant_optimizer_settings_use_case() -> GetAssistantOptimizerSettingsUseCase:
    return GetAssistantOptimizerSettingsUseCase(
        get_assistant_optimizer_settings_repository()
    )


def get_update_assistant_optimizer_settings_use_case() -> UpdateAssistantOptimizerSettingsUseCase:
    repository = get_assistant_optimizer_settings_repository()
    return UpdateAssistantOptimizerSettingsUseCase(
        repository,
        repository,
        get_audit_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_list_assistant_optimizer_settings_changes_use_case() -> (
    ListAssistantOptimizerSettingsChangesUseCase
):
    return ListAssistantOptimizerSettingsChangesUseCase(
        get_assistant_optimizer_settings_repository()
    )


def get_preview_mature_sample_use_case() -> PreviewMatureSampleUseCase:
    return PreviewMatureSampleUseCase(
        get_alert_repository(),
        get_operational_settings_repository(),
        get_assistant_optimizer_settings_repository(),
        get_alert_schema_repository(),
        get_dataset_sampler_state_repository(),
        clock=get_clock(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
    )


@lru_cache
def get_dataset_sampler_state_repository() -> DynamoDatasetSamplerStateRepository:
    return DynamoDatasetSamplerStateRepository()


@lru_cache
def get_mature_sample_executor() -> CeleryMatureSampleExecutor:
    return CeleryMatureSampleExecutor()


def get_start_mature_sample_use_case() -> CreateAsyncOperationUseCase:
    return CreateAsyncOperationUseCase(
        repository=get_async_operation_repository(),
        executor=get_mature_sample_executor(),
        supported_operation_types=frozenset({"mature_sample.create"}),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )
