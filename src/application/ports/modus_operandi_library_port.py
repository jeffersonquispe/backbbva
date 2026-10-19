from __future__ import annotations

from typing import Protocol

from src.domain.fraud_knowledge.library_entities import (
    ModusOperandiLibraryEntry,
    ModusOperandiPlaybook,
)


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
        evolved_variables: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
        playbook: ModusOperandiPlaybook | None = None,
    ) -> ModusOperandiLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
