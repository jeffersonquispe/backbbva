from __future__ import annotations

from functools import lru_cache

from src.application.ports.variable_catalog_port import VariableCatalogRepository
from src.application.use_cases.variable_catalog.create_variable import (
    CreateVariableUseCase,
)
from src.application.use_cases.variable_catalog.delete_variable import (
    DeleteVariableUseCase,
)
from src.application.use_cases.variable_catalog.list_variables import (
    ListVariablesUseCase,
)
from src.application.use_cases.variable_catalog.update_variable import (
    UpdateVariableUseCase,
)
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.persistence.database.dynamodb.repositories.variable_catalog_repository import (
    DynamoVariableCatalogRepository,
)


@lru_cache
def get_variable_catalog_repository() -> VariableCatalogRepository:
    return DynamoVariableCatalogRepository()


def get_create_variable_use_case() -> CreateVariableUseCase:
    return CreateVariableUseCase(
        get_variable_catalog_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_list_variables_use_case() -> ListVariablesUseCase:
    return ListVariablesUseCase(get_variable_catalog_repository())


def get_update_variable_use_case() -> UpdateVariableUseCase:
    return UpdateVariableUseCase(get_variable_catalog_repository())


def get_delete_variable_use_case() -> DeleteVariableUseCase:
    return DeleteVariableUseCase(get_variable_catalog_repository())
