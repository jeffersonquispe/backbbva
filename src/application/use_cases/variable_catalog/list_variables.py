from __future__ import annotations

from src.application.ports.variable_catalog_port import (
    VariableCatalogRepository,
    VariableEntry,
)


class ListVariablesUseCase:
    def __init__(self, variable_catalog_repository: VariableCatalogRepository) -> None:
        self._variables = variable_catalog_repository

    def execute(self, *, active_only: bool = False) -> list[VariableEntry]:
        return self._variables.list(active_only=active_only)
