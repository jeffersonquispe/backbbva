from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from src.application.ports.alert_port import AlertMetricsSnapshot


class MetricsDataType(StrEnum):
    """First component of a rollup row's key - each type uses only the
    dimensions that apply to it."""

    ALERT = "alert"
    WORKFLOW_STEP = "workflow_step"
    LLM_CALL = "llm_call"
    RESEARCH_CALL = "research_call"
    RESERVATION = "reservation"
    # Sampled LLM-judge verdicts on a finished alert's reasoning (D6).
    EVALUATION = "evaluation"


class RollupLevel(StrEnum):
    """Bucket granularity. Every level keeps 24 hour-of-day slots. Day rows
    only exist for dates < DAY_LEVEL_RETENTION_DAYS old in the operations
    timezone (Bogota); month and year rows always exist."""

    DAY = "day"
    MONTH = "month"
    YEAR = "year"


# Day rows are written only while the alert's local date is younger than
# this (age 0..89 days) and expire by TTL after it.
DAY_LEVEL_RETENTION_DAYS = 90

# Fixed order of the alert dimensions inside RollupKey.dimensions (and so of
# the serialized sort key). A missing value is stored as UNKNOWN_DIMENSION.
ALERT_DIMENSIONS: tuple[str, ...] = (
    "origin",
    "segment",
    "channel",
    "subchannel",
    "amount_tier",
    "schema_version",
    "status",
    "configuration_id",
    "resolution_method",
    "mark",
    "fraud_label",
)
UNKNOWN_DIMENSION = "unknown"

# Alert dimensions carried by the technical data types (workflow_step,
# llm_call, research_call, evaluation): the alert's dimensions as of the end
# of the workflow run that produced the row. mark and fraud_label are left
# out on purpose - they keep changing after the run (analyst, voicebot,
# fraud-team review) and technical rows are written once, never re-deltaed;
# status/resolution_method mean "as of the end of ARIA's run".
TECHNICAL_ALERT_DIMENSIONS: tuple[str, ...] = tuple(
    name for name in ALERT_DIMENSIONS if name not in ("mark", "fraud_label")
)
# Full dimension order per technical data type.
WORKFLOW_STEP_DIMENSIONS: tuple[str, ...] = TECHNICAL_ALERT_DIMENSIONS + ("step_name",)
LLM_CALL_DIMENSIONS: tuple[str, ...] = TECHNICAL_ALERT_DIMENSIONS + (
    "step_name",
    "model",
)
RESEARCH_CALL_DIMENSIONS: tuple[str, ...] = TECHNICAL_ALERT_DIMENSIONS + (
    "step_name",
    "source",
)
EVALUATION_DIMENSIONS: tuple[str, ...] = TECHNICAL_ALERT_DIMENSIONS


@dataclass(frozen=True)
class RollupKey:
    """One rollup row. period is "YYYY-MM-DD" (day), "YYYY-MM" (month) or
    "YYYY" (year), in the operations timezone. dimensions is an ordered
    tuple of (name, value) pairs - for alerts, exactly ALERT_DIMENSIONS."""

    data_type: MetricsDataType
    level: RollupLevel
    period: str
    dimensions: tuple[tuple[str, str], ...]

    def dimension(self, name: str) -> str | None:
        return dict(self.dimensions).get(name)


@dataclass(frozen=True)
class RollupDelta:
    """Signed increments for one hour-of-day slot (0-23, local time) of one
    row. Only additive measures (counts, sums, fixed-bucket histogram
    counts) - never averages, rates or distinct counts."""

    key: RollupKey
    hour: int
    measures: dict[str, float] = field(default_factory=dict)


@dataclass
class RollupRow:
    """A stored row: per measure, its 24 hour-of-day slots (index = hour)."""

    key: RollupKey
    measures: dict[str, list[float]] = field(default_factory=dict)
    # Bumped by every write to the row (apply, apply_once, correct) - lets
    # the reconciliation correct a row only if no live write touched it
    # since it was read. 0 = row stored before revisions existed.
    revision: int = 0

    def total(self, measure: str, hours: tuple[int, ...] | None = None) -> float:
        slots = self.measures.get(measure) or [0.0] * 24
        return sum(slots[h] for h in (hours if hours is not None else range(24)))


@dataclass(frozen=True)
class AlertSnapshotGuard:
    """The alert-side half of an apply(): write `snapshot` (whose
    snapshot_version must be expected_version + 1) onto the alert only if
    its stored snapshot is still at expected_version (0 = none stored).
    alert_created_at lets the adapter also fill the alert's created_day
    index attribute when it is missing (alerts older than that index)."""

    alert_id: UUID
    alert_created_at: datetime
    expected_version: int
    snapshot: AlertMetricsSnapshot


@dataclass(frozen=True)
class RollupApplyMarker:
    """Idempotency key for apply_once(): the deltas of one source event are
    applied at most once per (scope, key), ever. scope names the event kind
    ("workflow_step", "evaluation"), key identifies the event instance (the
    step execution id, the alert id). For events that have no alert
    snapshot to version (technical metrics, evaluations)."""

    scope: str
    key: str


class MetricsRollupRepository(Protocol):
    def apply(self, deltas: list[RollupDelta], alert_guard: AlertSnapshotGuard) -> None:
        """Atomically (one transaction): write the alert's new snapshot,
        conditioned on its snapshot_version, plus every delta as an
        additive increment. Nothing is written if the condition fails -
        raises domain.alerts.exceptions.SnapshotVersionConflictError, the
        caller re-reads and recomputes. Deltas for the same key are merged
        by the implementation."""
        ...

    def query(
        self,
        data_type: MetricsDataType,
        level: RollupLevel,
        periods: list[str],
        filters: dict[str, list[str]] | None = None,
    ) -> list[RollupRow]:
        """Rows of the given periods whose dimensions match every filter
        (dimension name -> accepted values; absent = any value)."""
        ...

    def apply_once(self, deltas: list[RollupDelta], marker: RollupApplyMarker) -> bool:
        """Atomically (one transaction): create `marker`, conditioned on it
        not existing yet, plus every delta as an additive increment.
        Returns True when applied, False when the marker already existed
        (this event was already counted - nothing is written). Deltas for
        the same key are merged by the implementation."""
        ...

    def correct(
        self,
        key: RollupKey,
        measures: dict[str, list[float]],
        expected_revision: int | None,
    ) -> bool:
        """R7 reconciliation only - never the live path. Make the row hold
        exactly `measures` (24 slots each; absent measures become 0), only
        if its revision is still `expected_revision` (None = the row must
        not exist yet). Returns False, writing nothing, when a write landed
        since the caller read the row. Never touches alert snapshots."""
        ...
