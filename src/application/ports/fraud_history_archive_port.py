from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class FraudHistoryDayArchive:
    """What archiving one Bogotá creation day moved (or would move)."""

    created_day: date
    alerts: int
    reviews: int
    held: int
    deleted: int
    object_key: str | None
    sha256: str | None


class FraudHistoryArchivePort(ABC):
    def archive_day(self, created_day: date, *, dry_run: bool) -> FraudHistoryDayArchive:
        """Move one day's alerts and fraud-label reviews to cold storage.

        The archive object is written and read back (SHA-256 checked) before
        any row is deleted; alerts under legal hold stay hot. A re-run of an
        already archived day is a no-op (nothing left to move)."""
        raise NotImplementedError
