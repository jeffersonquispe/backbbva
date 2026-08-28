from __future__ import annotations

from src.application.ports.variable_catalog_port import VariableCatalogRepository


class DeleteVariableUseCase:
    def __init__(self, variable_catalog_repository: VariableCatalogRepository) -> None:
        self._variables = variable_catalog_repository

    def execute(self, entry_id: str) -> None:
        self._variables.delete(entry_id)
