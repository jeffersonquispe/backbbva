from __future__ import annotations

from src.application.ports.tag_catalog_port import (
    TagCatalogRepository,
    TagCategory,
    TagEntry,
)


class TagNotFoundError(Exception):
    pass


class UpdateTagUseCase:
    def __init__(self, tag_catalog_repository: TagCatalogRepository) -> None:
        self._tags = tag_catalog_repository

    def execute(
        self,
        category: TagCategory,
        tag_id: str,
        *,
        value: str | None = None,
        active: bool | None = None,
    ) -> TagEntry:
        updated = self._tags.update(category, tag_id, value=value, active=active)
        if updated is None:
            raise TagNotFoundError(f"Tag not found: {category}/{tag_id}")
        return updated
