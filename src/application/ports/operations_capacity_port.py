from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ChannelCapacity:
    available: int
    status: str  # e.g. "available" | "degraded" | "unavailable"


@dataclass(frozen=True)
class OperationsCapacityRecord:
    analysts: ChannelCapacity
    voicebot: ChannelCapacity
    bidi: ChannelCapacity
    updated_at: datetime


class OperationsCapacityPort:
    """Current staffing/channel capacity snapshot used by the analyst
    decision step. One operational record, not per-channel lookups - the
    analyst agent needs the full picture (analysts, voicebot, bidi) in a
    single read."""

    def get_capacity(self) -> OperationsCapacityRecord:
        raise NotImplementedError
