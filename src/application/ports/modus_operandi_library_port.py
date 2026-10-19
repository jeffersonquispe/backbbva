from __future__ import annotations

import builtins
from datetime import datetime
from typing import Protocol

from src.domain.fraud_knowledge.library_entities import (
    ModusOperandiLibraryEntry,
    ModusOperandiPlaybook,
)


class ModusOperandiLibraryRevisionConflict(Exception):
    pass


class ModusOperandiLibraryRepository(Protocol):
    def create(self, entry: ModusOperandiLibraryEntry) -> ModusOperandiLibraryEntry: ...

    def get(self, entry_id: str) -> ModusOperandiLibraryEntry | None: ...

    def list(self, *, active_only: bool = False) -> list[ModusOperandiLibraryEntry]: ...

    def update(
        self,
        entry_id: str,
        *,
        title: str | None = None,
        narrative: str | None = None,
        taxonomy_library_id: str | None = None,
        evolved_variables: builtins.list[str] | None = None,
        active: bool | None = None,
        embedding: builtins.list[float] | None = None,
        playbook: ModusOperandiPlaybook | None = None,
        expected_updated_at: datetime | None = None,
    ) -> ModusOperandiLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
