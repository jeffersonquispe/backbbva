from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.application.ports.configuration_port import ResolutionTag


@dataclass
class ResolutionMethod:
    # Flat catalog, mirrors marcacion_catalog_port.py's MarcacionCategory -
    # `resolution_tag` is the fixed dimension (the 3 values the workflow
    # will eventually branch on, see configuration_port.py's
    # AnalystPlaybook comment), `value` is the admin-editable display name,
    # same relationship as MarcacionCategory.value -> RiskLabel.
    id: str
    value: str
    resolution_tag: ResolutionTag
    created_at: datetime
    updated_at: datetime
    active: bool = True


class ResolutionMethodCatalogRepository(Protocol):
    def create(self, entry: ResolutionMethod) -> ResolutionMethod:
        ...

    def get(self, entry_id: str) -> ResolutionMethod | None:
        ...

    def list(self, *, active_only: bool = False) -> list[ResolutionMethod]:
        ...

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        resolution_tag: ResolutionTag | None = None,
        active: bool | None = None,
    ) -> ResolutionMethod | None:
        ...

    def delete(self, entry_id: str) -> None:
        ...
