from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.tag_catalog_port import TagCatalogRepository
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.configurations.entities import (
    TagCategory,
)
from src.domain.tag_catalog.entities import TagEntry


class CreateTagUseCase:
    def __init__(
        self,
        tag_catalog_repository: TagCatalogRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._tags = tag_catalog_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, category: TagCategory, value: str) -> TagEntry:
        now = self._clock.now()
        return self._tags.create(
            TagEntry(
                id=str(self._id_generator.new_id()),
                category=category,
                value=value,
                created_at=now,
                updated_at=now,
            )
        )
