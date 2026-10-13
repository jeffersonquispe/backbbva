from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class VariableEntry:
    # Flat catalog, mirrors marcacion_catalog_port.py's MarcacionCategory -
    # no risk-label-like second dimension, just an optional human-readable
    # description (variable names alone, e.g. "Altamira", aren't
    # self-explanatory to a config admin picking from the pool).
    id: str
    value: str
    created_at: datetime
    updated_at: datetime
    description: str = ""
    active: bool = True


class VariableCatalogRepository(Protocol):
    def create(self, entry: VariableEntry) -> VariableEntry: ...

    def get(self, entry_id: str) -> VariableEntry | None: ...

    def list(self, *, active_only: bool = False) -> list[VariableEntry]: ...

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> VariableEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
