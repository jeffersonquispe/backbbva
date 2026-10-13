from __future__ import annotations

from src.application.errors import NotFoundError
from src.application.ports.marcacion_catalog_port import (
    MarcacionCatalogRepository,
    MarcacionCategory,
    RiskLabel,
)


class MarcacionCategoryNotFoundError(NotFoundError):
    pass


class UpdateMarcacionCategoryUseCase:
    def __init__(
        self, marcacion_catalog_repository: MarcacionCatalogRepository
    ) -> None:
        self._categories = marcacion_catalog_repository

    def execute(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        risk_label: RiskLabel | None = None,
        active: bool | None = None,
    ) -> MarcacionCategory:
        updated = self._categories.update(
            entry_id, value=value, risk_label=risk_label, active=active
        )
        if updated is None:
            raise MarcacionCategoryNotFoundError(
                f"Marcación category not found: {entry_id}"
            )
        return updated
