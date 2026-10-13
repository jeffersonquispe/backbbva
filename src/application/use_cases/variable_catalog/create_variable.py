from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.variable_catalog_port import (
    VariableCatalogRepository,
    VariableEntry,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class CreateVariableUseCase:
    def __init__(
        self,
        variable_catalog_repository: VariableCatalogRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._variables = variable_catalog_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, value: str, description: str = "") -> VariableEntry:
        now = self._clock.now()
        return self._variables.create(
            VariableEntry(
                id=str(self._id_generator.new_id()),
                value=value,
                description=description,
                created_at=now,
                updated_at=now,
            )
        )
