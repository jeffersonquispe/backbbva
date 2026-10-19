from __future__ import annotations

from typing import Protocol

from src.domain.configurations.entities import TagCategory
from src.domain.tag_catalog.entities import TagEntry


class TagCatalogRepository(Protocol):
    def create(self, entry: TagEntry) -> TagEntry: ...

    def get(self, category: TagCategory, tag_id: str) -> TagEntry | None: ...

    def list_by_category(
        self, category: TagCategory, *, active_only: bool = False
    ) -> list[TagEntry]: ...

    def update(
        self,
        category: TagCategory,
        tag_id: str,
        *,
        value: str | None = None,
        active: bool | None = None,
    ) -> TagEntry | None: ...

    def delete(self, category: TagCategory, tag_id: str) -> None: ...
