from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.domain.configurations.entities import TagCategory


@dataclass
class TagEntry:
    id: str
    category: TagCategory
    value: str
    created_at: datetime
    updated_at: datetime
    active: bool = True


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
