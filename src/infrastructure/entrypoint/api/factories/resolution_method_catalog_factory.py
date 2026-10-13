from __future__ import annotations

from functools import lru_cache

from src.application.use_cases.resolution_method_catalog.create_resolution_method import (
    CreateResolutionMethodUseCase,
)
from src.application.use_cases.resolution_method_catalog.delete_resolution_method import (
    DeleteResolutionMethodUseCase,
)
from src.application.use_cases.resolution_method_catalog.list_resolution_methods import (
    ListResolutionMethodsUseCase,
)
from src.application.use_cases.resolution_method_catalog.update_resolution_method import (
    UpdateResolutionMethodUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.resolution_method_catalog_repository import (
    DynamoResolutionMethodCatalogRepository,
)


@lru_cache
def get_resolution_method_catalog_repository() -> (
    DynamoResolutionMethodCatalogRepository
):
    return DynamoResolutionMethodCatalogRepository()


def get_create_resolution_method_use_case() -> CreateResolutionMethodUseCase:
    return CreateResolutionMethodUseCase(get_resolution_method_catalog_repository())


def get_list_resolution_methods_use_case() -> ListResolutionMethodsUseCase:
    return ListResolutionMethodsUseCase(get_resolution_method_catalog_repository())


def get_update_resolution_method_use_case() -> UpdateResolutionMethodUseCase:
    return UpdateResolutionMethodUseCase(get_resolution_method_catalog_repository())


def get_delete_resolution_method_use_case() -> DeleteResolutionMethodUseCase:
    return DeleteResolutionMethodUseCase(get_resolution_method_catalog_repository())
