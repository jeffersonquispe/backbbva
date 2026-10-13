from __future__ import annotations

from src.application.ports.marcacion_catalog_port import MarcacionCatalogRepository


class DeleteMarcacionCategoryUseCase:
    def __init__(
        self, marcacion_catalog_repository: MarcacionCatalogRepository
    ) -> None:
        self._categories = marcacion_catalog_repository

    def execute(self, entry_id: str) -> None:
        self._categories.delete(entry_id)
