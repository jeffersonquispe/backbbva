from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field


@dataclass(frozen=True)
class E2EStateCleanResult:
    deleted_items: int
    preserved_tables: list[str] = field(default_factory=list)
    table_count: int = 0


class E2EStateCleaner(ABC):
    def clean(self) -> E2EStateCleanResult:
        """Delete application data for the E2E suite, keeping the tables
        the suite needs to stay logged in (e.g. users)."""
        raise NotImplementedError
