from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass
class ChannelLibraryEntry:
    # Global, config-independent reference data replacing the old fixed
    # SegmentCode enum ("canales_digitales"/"tarjetas") - a config's
    # segments dict is (and always was) keyed by plain string, so this
    # catalog just makes that set of keys admin-editable instead of a
    # hardcoded enum. Snapshot-copied into a new configuration's segments
    # at creation time (frontend's defaultSegments(), mirroring
    # taxonomy_library_port.py's import-not-reference semantics) - editing
    # or deactivating an entry here never touches an already-built config.
    # Unrelated to operations_capacity_port.py's ChannelCapacity (that one
    # is a staffing/resource snapshot for analysts/voicebot/bidi, not a
    # business segment).
    id: str
    code: str
    name: str
    description: str
    created_at: datetime
    updated_at: datetime
    active: bool = True


class ChannelLibraryRepository(Protocol):
    def create(self, entry: ChannelLibraryEntry) -> ChannelLibraryEntry: ...

    def get(self, entry_id: str) -> ChannelLibraryEntry | None: ...

    def list(self, *, active_only: bool = False) -> list[ChannelLibraryEntry]: ...

    def update(
        self,
        entry_id: str,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
        active: bool | None = None,
    ) -> ChannelLibraryEntry | None: ...

    def delete(self, entry_id: str) -> None: ...
