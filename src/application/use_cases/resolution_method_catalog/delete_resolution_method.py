from __future__ import annotations

from src.application.ports.resolution_method_catalog_port import (
    ResolutionMethodCatalogRepository,
)


class DeleteResolutionMethodUseCase:
    def __init__(
        self, resolution_method_catalog_repository: ResolutionMethodCatalogRepository
    ) -> None:
        self._methods = resolution_method_catalog_repository

    def execute(self, entry_id: str) -> None:
        self._methods.delete(entry_id)
