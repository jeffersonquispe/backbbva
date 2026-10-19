from __future__ import annotations

import builtins
from typing import Protocol

from src.domain.configurations.entities import (
    FlagType,
)
from src.domain.fraud_knowledge.library_entities import FlagLibraryEntry


class FlagLibraryRepository(Protocol):
    def create(self, entry: FlagLibraryEntry) -> FlagLibraryEntry: ...

    def get(self, entry_id: str) -> FlagLibraryEntry | None: ...

    def list(self, *, active_only: bool = False) -> list[FlagLibraryEntry]: ...

    def update(
        self,
        entry_id: str,
        *,
        flag_type: FlagType | None = None,
        name: str | None = None,
        description: str | None = None,
        evolved_variables: builtins.list[str] | None = None,
        modus_operandi_library_ids: builtins.list[str] | None = None,
        active: bool | None = None,
        embedding: builtins.list[float] | None = None,
    ) -> FlagLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
