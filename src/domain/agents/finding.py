"""Aggregated findings and cross-session optimizer memory."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

# A pattern is only published when its segment has at least this many cases.
MIN_SUPPORT = 30


class AgentFindingKind(StrEnum):
    DIAGNOSTIC = "DIAGNOSTIC"
    PATTERN = "PATTERN"


@dataclass(frozen=True)
class AgentFinding:
    """Aggregated output of the diagnosis (B2.5) or pattern discovery (B2.6)."""

    session_id: str
    finding_id: str
    kind: AgentFindingKind
    dimension: str  # segment, channel, subchannel, stage or route
    dimension_value: str
    sample_count: int
    metrics: dict[str, float]
    source: str  # rollups, judge, training
    created_at: datetime
    period_start: str | None = None
    period_end: str | None = None
    opaque_refs: dict[str, str] = field(default_factory=dict)
    expires_at: int | None = None


class OptimizerInsightKind(StrEnum):
    PATTERN = "PATTERN"
    HYPOTHESIS = "HYPOTHESIS"


class OptimizerInsightStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    STALE = "STALE"
    RETIRED = "RETIRED"


@dataclass(frozen=True)
class OptimizerInsight:
    """Data-backed finding that outlives the session that produced it."""

    insight_id: str
    statement: str
    kind: OptimizerInsightKind
    scope_key: str
    status: OptimizerInsightStatus
    sample_count: int
    created_at: datetime
    last_evaluated_at: datetime
    review_after: datetime
    evidence_summary: dict[str, float] = field(default_factory=dict)
    period_start: str | None = None
    period_end: str | None = None
    dataset_snapshot_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    schema_version: str | None = None
    origin_session_id: str | None = None
    origin_run_id: str | None = None
    supersedes_id: str | None = None
    rev: int = 0

    def __post_init__(self) -> None:
        if self.sample_count < MIN_SUPPORT:
            raise ValueError("INSIGHT_SUPPORT_TOO_LOW")
