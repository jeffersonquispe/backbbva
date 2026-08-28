from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.variable_catalog_port import (
    VariableCatalogRepository,
    VariableEntry,
)


class CreateVariableUseCase:
    def __init__(self, variable_catalog_repository: VariableCatalogRepository) -> None:
        self._variables = variable_catalog_repository

    def execute(self, value: str, description: str = "") -> VariableEntry:
        now = datetime.now(timezone.utc)
        return self._variables.create(
            VariableEntry(
                id=str(uuid.uuid4()),
                value=value,
                description=description,
                created_at=now,
                updated_at=now,
            )
        )
