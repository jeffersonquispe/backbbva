from __future__ import annotations

from functools import lru_cache

from src.application.ports.marcacion_catalog_port import MarcacionCatalogRepository
from src.application.use_cases.marcacion_catalog.create_marcacion_category import (
    CreateMarcacionCategoryUseCase,
)
from src.application.use_cases.marcacion_catalog.delete_marcacion_category import (
    DeleteMarcacionCategoryUseCase,
)
from src.application.use_cases.marcacion_catalog.list_marcacion_categories import (
    ListMarcacionCategoriesUseCase,
)
from src.application.use_cases.marcacion_catalog.update_marcacion_category import (
    UpdateMarcacionCategoryUseCase,
)
from src.infrastructure.persistence.database.dynamodb.repositories.marcacion_catalog_repository import (
    DynamoMarcacionCatalogRepository,
)


@lru_cache
def get_marcacion_catalog_repository() -> MarcacionCatalogRepository:
    return DynamoMarcacionCatalogRepository()


def get_create_marcacion_category_use_case() -> CreateMarcacionCategoryUseCase:
    return CreateMarcacionCategoryUseCase(get_marcacion_catalog_repository())


def get_list_marcacion_categories_use_case() -> ListMarcacionCategoriesUseCase:
    return ListMarcacionCategoriesUseCase(get_marcacion_catalog_repository())


def get_update_marcacion_category_use_case() -> UpdateMarcacionCategoryUseCase:
    return UpdateMarcacionCategoryUseCase(get_marcacion_catalog_repository())


def get_delete_marcacion_category_use_case() -> DeleteMarcacionCategoryUseCase:
    return DeleteMarcacionCategoryUseCase(get_marcacion_catalog_repository())
