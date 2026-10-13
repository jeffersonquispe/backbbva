from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class VersionEvent:
    kind: str
    label: str
    version: int
    configuration_id: str | None
    at: datetime


class VersionEventsSource(Protocol):
    def list_version_events(self, from_: datetime, to: datetime) -> list[VersionEvent]: ...
