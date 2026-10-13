from __future__ import annotations

from functools import lru_cache

from src.application.ports.operational_settings_port import (
    OperationalSettingsRepository,
)
from src.application.use_cases.operational_settings.get_operational_settings import (
    GetOperationalSettingsUseCase,
)
from src.application.use_cases.operational_settings.list_operational_settings_history import (
    ListOperationalSettingsHistoryUseCase,
)
from src.application.use_cases.operational_settings.update_operational_settings import (
    UpdateOperationalSettingsUseCase,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.persistence.database.dynamodb.repositories.operational_settings_repository import (
    DynamoOperationalSettingsRepository,
)


@lru_cache
def get_operational_settings_repository() -> OperationalSettingsRepository:
    return DynamoOperationalSettingsRepository()


def get_get_operational_settings_use_case() -> GetOperationalSettingsUseCase:
    return GetOperationalSettingsUseCase(get_operational_settings_repository())


def get_update_operational_settings_use_case() -> UpdateOperationalSettingsUseCase:
    return UpdateOperationalSettingsUseCase(
        get_operational_settings_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_list_operational_settings_history_use_case() -> (
    ListOperationalSettingsHistoryUseCase
):
    return ListOperationalSettingsHistoryUseCase(get_operational_settings_repository())
