"""Append-only timeline of what an optimizer/assistant session did."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class AgentEventKind(StrEnum):
    SESSION = "session"
    ITERATION = "iteration"
    HYPOTHESIS = "hypothesis"
    SPECIALIST = "specialist"
    EXPERIMENT = "experiment"
    VERIFICATION = "verification"
    DECISION = "decision"
    BUDGET = "budget"
    RECOVERY = "recovery"
    BLOCKED = "blocked"
    USER_ACTION = "user_action"
    PRODUCTION_CHANGE = "production_change"


class AgentEventOutcome(StrEnum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    INFO = "INFO"


# Opaque reference names an event may carry. Anything else is dropped so rows,
# customer ids, amounts and prompt text can never land on the timeline.
ALLOWED_REF_KEYS = frozenset(
    {
        "iteration",
        "hypothesis_id",
        "insight_id",
        "finding_id",
        "experiment_id",
        "run_id",
        "verification_id",
        "package_id",
        "release_id",
        "snapshot_id",
        "audit_correlation_id",
        "specialist",
    }
)


def safe_refs(refs: dict[str, object] | None) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in (refs or {}).items()
        if key in ALLOWED_REF_KEYS and value is not None
    }


@dataclass(frozen=True)
class AgentEvent:
    session_id: str
    seq: int
    event_id: str
    occurred_at: datetime
    kind: AgentEventKind
    outcome: AgentEventOutcome
    summary: str
    reason_code: str | None = None
    refs: dict[str, str] = field(default_factory=dict)
    duration_ms: int | None = None
    cost_micros: int | None = None
    actor_id: str | None = None
    expires_at: int | None = None
