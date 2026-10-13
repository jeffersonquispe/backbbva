from __future__ import annotations

from src.application.ports.marcacion_catalog_port import (
    MarcacionCatalogRepository,
    MarcacionCategory,
)


class ListMarcacionCategoriesUseCase:
    def __init__(
        self, marcacion_catalog_repository: MarcacionCatalogRepository
    ) -> None:
        self._categories = marcacion_catalog_repository

    def execute(self, *, active_only: bool = False) -> list[MarcacionCategory]:
        return self._categories.list(active_only=active_only)
