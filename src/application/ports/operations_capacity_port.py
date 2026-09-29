from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ChannelCapacity:
    available: int
    # "available" | "exhausted" (on, but every slot/analyst is taken) |
    # "unavailable" (switched off in OperationalSettings)
    status: str
    # The quota `available` is measured against (voicebot slots, or the
    # analyst matrix value for the current hour). None when not tracked.
    total: int | None = None


@dataclass(frozen=True)
class OperationsCapacityRecord:
    analysts: ChannelCapacity
    voicebot: ChannelCapacity
    bidi: ChannelCapacity
    updated_at: datetime


class OperationsCapacityPort:
    """Current staffing/channel capacity snapshot used by the analyst
    decision step and the executor. One operational record, not per-channel
    lookups - the analyst agent needs the full picture (analysts, voicebot,
    bidi) in a single read. The live implementation is LiveOperationsCapacity
    (use_cases/operations/live_operations_capacity.py)."""

    def get_capacity(self) -> OperationsCapacityRecord:
        raise NotImplementedError
