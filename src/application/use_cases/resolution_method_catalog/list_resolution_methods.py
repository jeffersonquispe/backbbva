from __future__ import annotations

from src.application.ports.resolution_method_catalog_port import (
    ResolutionMethod,
    ResolutionMethodCatalogRepository,
)


class ListResolutionMethodsUseCase:
    def __init__(
        self, resolution_method_catalog_repository: ResolutionMethodCatalogRepository
    ) -> None:
        self._methods = resolution_method_catalog_repository

    def execute(self, *, active_only: bool = False) -> list[ResolutionMethod]:
        return self._methods.list(active_only=active_only)
