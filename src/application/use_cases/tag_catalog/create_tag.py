from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.tag_catalog_port import (
    TagCatalogRepository,
    TagCategory,
    TagEntry,
)


class CreateTagUseCase:
    def __init__(self, tag_catalog_repository: TagCatalogRepository) -> None:
        self._tags = tag_catalog_repository

    def execute(self, category: TagCategory, value: str) -> TagEntry:
        now = datetime.now(UTC)
        return self._tags.create(
            TagEntry(
                id=str(uuid.uuid4()),
                category=category,
                value=value,
                created_at=now,
                updated_at=now,
            )
        )
