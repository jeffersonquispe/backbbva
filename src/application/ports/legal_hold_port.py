from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class LegalHold:
    alert_id: str
    reason: str
    case_reference: str | None
    placed_by: str
    placed_at: datetime
    released_at: datetime | None = None
    released_by: str | None = None
    release_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.released_at is None


class LegalHoldRepository(Protocol):
    def place(self, hold: LegalHold) -> bool:
        """Store an active hold. ``False`` when one is already active."""
        ...

    def release(
        self,
        alert_id: str,
        *,
        released_by: str,
        release_reason: str,
        released_at: datetime,
    ) -> LegalHold | None:
        """Close the active hold; ``None`` when there is none."""
        ...

    def get(self, alert_id: str) -> LegalHold | None: ...

    def list_active(self, limit: int = 100) -> list[LegalHold]: ...

    def active_ids(self, alert_ids: Sequence[str]) -> set[str]:
        """Which of ``alert_ids`` have an active hold."""
        ...
