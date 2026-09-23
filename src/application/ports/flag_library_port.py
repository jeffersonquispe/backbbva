from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from src.application.ports.configuration_port import FlagType


@dataclass
class FlagLibraryEntry:
    # Global, config-independent reference data - see taxonomy_library_port.py
    # for the snapshot-copy rationale. modus_operandi_library_ids is
    # many-to-many with ModusOperandiLibraryEntry, mirroring
    # configuration_port.py's Flag (no taxonomy_library_id - a flag's
    # taxonomy is derived from whichever MO it's attached to).
    id: str
    flag_type: FlagType
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    evolved_variables: list[str] = field(default_factory=list)
    modus_operandi_library_ids: list[str] = field(default_factory=list)
    active: bool = True
    # Cached embedding of this entry's text representation (name +
    # description) - see taxonomy_library_port.py's `embedding` field for
    # the recycle-on-promote rationale.
    embedding: list[float] | None = None


class FlagLibraryRepository(Protocol):
    def create(self, entry: FlagLibraryEntry) -> FlagLibraryEntry:
        ...

    def get(self, entry_id: str) -> FlagLibraryEntry | None:
        ...

    def list(self, *, active_only: bool = False) -> list[FlagLibraryEntry]:
        ...

    def update(
        self,
        entry_id: str,
        *,
        flag_type: FlagType | None = None,
        name: str | None = None,
        description: str | None = None,
        evolved_variables: list[str] | None = None,
        modus_operandi_library_ids: list[str] | None = None,
        active: bool | None = None,
        embedding: list[float] | None = None,
    ) -> FlagLibraryEntry | None:
        ...

    def delete(self, entry_id: str) -> None:
        ...
