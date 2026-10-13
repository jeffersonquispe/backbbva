from __future__ import annotations

from src.application.ports.tag_catalog_port import (
    TagCatalogRepository,
)
from src.domain.configurations.entities import (
    TagCategory,
)


class DeleteTagUseCase:
    def __init__(self, tag_catalog_repository: TagCatalogRepository) -> None:
        self._tags = tag_catalog_repository

    def execute(self, category: TagCategory, tag_id: str) -> None:
        self._tags.delete(category, tag_id)
