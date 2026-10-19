from __future__ import annotations

from functools import lru_cache

from src.application.use_cases.assistant_optimizer_settings import (
    GetAssistantOptimizerSettingsUseCase,
    ListAssistantOptimizerSettingsChangesUseCase,
    UpdateAssistantOptimizerSettingsUseCase,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.persistence.database.dynamodb.audit_factory import (
    get_audit_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.assistant_optimizer_settings_repository import (
    DynamoAssistantOptimizerSettingsRepository,
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
