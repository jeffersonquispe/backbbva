from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from src.domain.configurations.entities import (
    ResolutionTag,
)


@dataclass
class ResolutionMethod:
    # Flat catalog, mirrors marcacion_catalog_port.py's MarcacionCategory -
    # `resolution_tag` is the fixed dimension the executor branches on (see
    # ModusOperandiPlaybook in domain/fraud_knowledge/library_entities.py: its primary
    # method uses the 3 routing tags, its fallbacks also allow
    # BLOCK_SOFT/BLOCK_HARD), `value` is the admin-editable display name,
    # same relationship as MarcacionCategory.value -> RiskLabel. Same catalog
    # is shared by both consumers - an admin names a method once and it's
    # pickable wherever a resolution_method_id field exists.
    id: str
    value: str
    resolution_tag: ResolutionTag
    created_at: datetime
    updated_at: datetime
    active: bool = True


class ResolutionMethodCatalogRepository(Protocol):
    def create(self, entry: ResolutionMethod) -> ResolutionMethod: ...

    def get(self, entry_id: str) -> ResolutionMethod | None: ...

    def list(self, *, active_only: bool = False) -> list[ResolutionMethod]: ...

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        resolution_tag: ResolutionTag | None = None,
        active: bool | None = None,
    ) -> ResolutionMethod | None: ...

    def delete(self, entry_id: str) -> None: ...
