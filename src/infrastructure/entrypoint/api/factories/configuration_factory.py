from __future__ import annotations

from functools import lru_cache

from src.application.ports.configuration_port import ConfigurationRepository
from src.application.use_cases.configurations.activate_configuration import (
    ActivateConfigurationUseCase,
)
from src.application.use_cases.configurations.create_configuration import (
    CreateConfigurationUseCase,
)
from src.application.use_cases.configurations.get_active_configuration import (
    GetActiveConfigurationUseCase,
)
from src.application.use_cases.configurations.get_configuration import (
    GetConfigurationUseCase,
)
from src.application.use_cases.configurations.list_configuration_versions import (
    ListConfigurationVersionsUseCase,
)
from src.application.use_cases.configurations.list_configurations import (
    ListConfigurationsUseCase,
)
from src.application.use_cases.configurations.test_configuration import (
    PreviewConfigurationUseCase,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.entrypoint.api.factories.test_run_factory import (
    get_test_run_repository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    DynamoConfigurationRepository,
)


@lru_cache
def get_configuration_repository() -> ConfigurationRepository:
    return DynamoConfigurationRepository()


def get_create_configuration_use_case() -> CreateConfigurationUseCase:
    return CreateConfigurationUseCase(
        get_configuration_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_get_configuration_use_case() -> GetConfigurationUseCase:
    return GetConfigurationUseCase(get_configuration_repository())


def get_list_configurations_use_case() -> ListConfigurationsUseCase:
    return ListConfigurationsUseCase(get_configuration_repository())


def get_list_configuration_versions_use_case() -> ListConfigurationVersionsUseCase:
    return ListConfigurationVersionsUseCase(get_configuration_repository())


def get_activate_configuration_use_case() -> ActivateConfigurationUseCase:
    return ActivateConfigurationUseCase(
        get_configuration_repository(),
        get_test_run_repository(),
    )


def get_get_active_configuration_use_case() -> GetActiveConfigurationUseCase:
    return GetActiveConfigurationUseCase(get_configuration_repository())


def get_test_configuration_use_case() -> PreviewConfigurationUseCase:
    return PreviewConfigurationUseCase(get_configuration_repository())
