from __future__ import annotations

from functools import lru_cache

from src.application.ports.tag_catalog_port import TagCatalogRepository
from src.application.use_cases.tag_catalog.create_tag import CreateTagUseCase
from src.application.use_cases.tag_catalog.delete_tag import DeleteTagUseCase
from src.application.use_cases.tag_catalog.list_tags import ListTagsUseCase
from src.application.use_cases.tag_catalog.update_tag import UpdateTagUseCase
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.persistence.database.dynamodb.repositories.tag_catalog_repository import (
    DynamoTagCatalogRepository,
)


@lru_cache
def get_tag_catalog_repository() -> TagCatalogRepository:
    return DynamoTagCatalogRepository()


def get_create_tag_use_case() -> CreateTagUseCase:
    return CreateTagUseCase(
        get_tag_catalog_repository(), clock=get_clock(), id_generator=get_id_generator()
    )


def get_list_tags_use_case() -> ListTagsUseCase:
    return ListTagsUseCase(get_tag_catalog_repository())


def get_update_tag_use_case() -> UpdateTagUseCase:
    return UpdateTagUseCase(get_tag_catalog_repository())


def get_delete_tag_use_case() -> DeleteTagUseCase:
    return DeleteTagUseCase(get_tag_catalog_repository())
