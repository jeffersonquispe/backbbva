from __future__ import annotations

from src.application.errors import NotFoundError
from src.application.ports.variable_catalog_port import (
    VariableCatalogRepository,
    VariableEntry,
)


class VariableNotFoundError(NotFoundError):
    pass


class UpdateVariableUseCase:
    def __init__(self, variable_catalog_repository: VariableCatalogRepository) -> None:
        self._variables = variable_catalog_repository

    def execute(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> VariableEntry:
        updated = self._variables.update(
            entry_id, value=value, description=description, active=active
        )
        if updated is None:
            raise VariableNotFoundError(f"Variable not found: {entry_id}")
        return updated
