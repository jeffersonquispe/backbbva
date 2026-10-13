from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.resolution_method_catalog_port import (
    ResolutionMethod,
    ResolutionMethodCatalogRepository,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.configurations.entities import (
    ResolutionTag,
)


class CreateResolutionMethodUseCase:
    def __init__(
        self,
        resolution_method_catalog_repository: ResolutionMethodCatalogRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._methods = resolution_method_catalog_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, value: str, resolution_tag: ResolutionTag) -> ResolutionMethod:
        now = self._clock.now()
        return self._methods.create(
            ResolutionMethod(
                id=str(self._id_generator.new_id()),
                value=value,
                resolution_tag=resolution_tag,
                created_at=now,
                updated_at=now,
            )
        )
