from __future__ import annotations

from src.application.ports.tag_catalog_port import (
    TagCatalogRepository,
    TagEntry,
)
from src.domain.configurations.entities import (
    TagCategory,
)


class ListTagsUseCase:
    def __init__(self, tag_catalog_repository: TagCatalogRepository) -> None:
        self._tags = tag_catalog_repository

    def execute(
        self, category: TagCategory, *, active_only: bool = False
    ) -> list[TagEntry]:
        return self._tags.list_by_category(category, active_only=active_only)
