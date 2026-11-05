from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from datetime import date
from typing import Any


class ArchiveVerificationError(RuntimeError):
    """Archived bytes no longer match the digest recorded for them."""


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
    def archive_day(
        self, created_day: date, *, dry_run: bool
    ) -> FraudHistoryDayArchive:
        """Move one day's alerts and fraud-label reviews to cold storage.

        The archive object is written and read back (SHA-256 checked) and every
        moved alert is indexed by ``alert_id`` before any row is deleted;
        alerts under legal hold stay hot. A re-run of an already archived day
        is a no-op (nothing left to move)."""
        raise NotImplementedError


@dataclass(frozen=True)
class ArchiveIndexEntry:
    """Where one archived alert lives inside its day object.

    ``offset``/``length`` address the alert's own gzip member, so it can be read
    with one range request. Both are ``None`` for objects written before the
    index existed (one gzip stream per day): those are read whole.
    """

    alert_id: str
    created_day: date
    object_key: str
    offset: int | None = None
    length: int | None = None
    record_sha256: str | None = None
    # The identifier that travels between systems; None for entries indexed
    # before it was recorded.
    event_id: str | None = None


@dataclass(frozen=True)
class ArchivedAlert:
    alert_id: str
    created_day: date
    object_key: str
    alert: dict[str, Any]
    fraud_label_reviews: list[dict[str, Any]] = field(default_factory=list)
    # Which digest the content was checked against: the alert's own record
    # ("record") or the whole day object, named by its SHA-256 ("object").
    verified_against: str = "record"


@dataclass(frozen=True)
class ArchivedAlertSummary:
    """What the index alone knows about an archived alert (no object read)."""

    alert_id: str
    event_id: str | None
    created_day: date


@dataclass(frozen=True)
class ArchiveIndexBackfillResult:
    objects: int
    alerts: int
    indexed: int
    already_indexed: int
