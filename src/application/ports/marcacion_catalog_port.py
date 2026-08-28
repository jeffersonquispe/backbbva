from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class RiskLabel(StrEnum):
    RISK_SUSPECTED = "risk-suspected"
    NO_RISK = "no-risk"


@dataclass
class MarcacionCategory:
    # Flat catalog, unlike tag_catalog_port.py's TagCategory-partitioned
    # TagEntry - marcación only ever has one dimension (the reason), no
    # category partition needed.
    id: str
    value: str
    risk_label: RiskLabel
    created_at: datetime
    updated_at: datetime
    active: bool = True


class MarcacionCatalogRepository(Protocol):
    def create(self, entry: MarcacionCategory) -> MarcacionCategory:
        ...

    def get(self, entry_id: str) -> MarcacionCategory | None:
        ...

    def list(self, *, active_only: bool = False) -> list[MarcacionCategory]:
        ...

    def update(
        self,
        entry_id: str,
        *,
        value: str | None = None,
        risk_label: RiskLabel | None = None,
        active: bool | None = None,
    ) -> MarcacionCategory | None:
        ...

    def delete(self, entry_id: str) -> None:
        ...
