from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.marcacion_catalog_port import (
    MarcacionCatalogRepository,
    MarcacionCategory,
    RiskLabel,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)


class CreateMarcacionCategoryUseCase:
    def __init__(
        self,
        marcacion_catalog_repository: MarcacionCatalogRepository,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._categories = marcacion_catalog_repository
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, value: str, risk_label: RiskLabel) -> MarcacionCategory:
        now = self._clock.now()
        return self._categories.create(
            MarcacionCategory(
                id=str(self._id_generator.new_id()),
                value=value,
                risk_label=risk_label,
                created_at=now,
                updated_at=now,
            )
        )
