from __future__ import annotations

from functools import lru_cache

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
from src.application.use_cases.configurations.index_configuration_knowledge import (
    IndexConfigurationKnowledgeUseCase,
)
from src.application.use_cases.configurations.list_configuration_versions import (
    ListConfigurationVersionsUseCase,
)
from src.application.use_cases.configurations.list_configurations import (
    ListConfigurationsUseCase,
)
from src.infrastructure.entrypoint.api.factories.fraud_knowledge_factory import (
    get_fraud_knowledge_repository,
    get_ingest_modus_operandi_use_case,
    get_ingest_red_flag_use_case,
    get_ingest_similar_case_use_case,
    get_ingest_taxonomia_use_case,
    get_ingest_yellow_flag_use_case,
)
from src.infrastructure.persistence.database.dynamodb.repositories.configuration_repository import (
    DynamoConfigurationRepository,
)


@lru_cache
def get_configuration_repository() -> DynamoConfigurationRepository:
    return DynamoConfigurationRepository()


def get_index_configuration_knowledge_use_case() -> IndexConfigurationKnowledgeUseCase:
    return IndexConfigurationKnowledgeUseCase(
        ingest_taxonomia=get_ingest_taxonomia_use_case(),
        ingest_modus_operandi=get_ingest_modus_operandi_use_case(),
        ingest_red_flag=get_ingest_red_flag_use_case(),
        ingest_yellow_flag=get_ingest_yellow_flag_use_case(),
        ingest_similar_case=get_ingest_similar_case_use_case(),
    )


def get_create_configuration_use_case() -> CreateConfigurationUseCase:
    return CreateConfigurationUseCase(
        get_configuration_repository(),
        get_index_configuration_knowledge_use_case(),
    )


def get_get_configuration_use_case() -> GetConfigurationUseCase:
    return GetConfigurationUseCase(get_configuration_repository())


def get_list_configurations_use_case() -> ListConfigurationsUseCase:
    return ListConfigurationsUseCase(get_configuration_repository())


def get_list_configuration_versions_use_case() -> ListConfigurationVersionsUseCase:
    return ListConfigurationVersionsUseCase(get_configuration_repository())


def get_activate_configuration_use_case() -> ActivateConfigurationUseCase:
    return ActivateConfigurationUseCase(
        get_configuration_repository(), get_fraud_knowledge_repository()
    )


def get_get_active_configuration_use_case() -> GetActiveConfigurationUseCase:
    return GetActiveConfigurationUseCase(get_configuration_repository())
