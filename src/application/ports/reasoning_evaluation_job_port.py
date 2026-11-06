from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ReasoningEvaluationJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    EVALUATED = "evaluated"
    # The judge answered but not in a usable shape, even after retrying.
    INVALID = "invalid"
    # The job could not run (provider down, retries exhausted).
    FAILED = "failed"


ACTIVE_STATUSES = frozenset(
    {ReasoningEvaluationJobStatus.QUEUED, ReasoningEvaluationJobStatus.RUNNING}
)


@dataclass
class ReasoningEvaluationJob:
    """The state of one alert's evaluation, kept apart from the alert and its
    workflow: the alert is resolved and visible whether or not this job ever
    runs, and a failed job never touches the alert."""

    alert_id: UUID
    workflow_execution_id: UUID
    status: ReasoningEvaluationJobStatus
    # "workflow" (sampled when the alert finished), "manual" (someone asked for it).
    requested_by: str
    queued_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Runs started (a retry or a recovery adds one).
    attempts: int = 0
    # Safe code only (never provider text) when status is FAILED.
    error_code: str | None = None
    # Milliseconds spent on the judge LLM in the last run.
    run_ms: int = 0

    @property
    def wait_ms(self) -> int | None:
        """Time between queueing and the first moment it started running."""
        if self.started_at is None:
            return None
        return int((self.started_at - self.queued_at).total_seconds() * 1000)

    @property
    def total_ms(self) -> int | None:
        """Queueing to a verdict: what "how long until I see it" means."""
        if self.finished_at is None:
            return None
        return int((self.finished_at - self.queued_at).total_seconds() * 1000)


class ReasoningEvaluationJobRepository(Protocol):
    def create_if_absent(self, job: ReasoningEvaluationJob) -> bool:
        """Store a new job; ``False`` when the alert already has one."""
        ...

    def get(self, alert_id: UUID) -> ReasoningEvaluationJob | None: ...

    def requeue(self, job: ReasoningEvaluationJob) -> bool:
        """Replace a FAILED or INVALID job with a fresh QUEUED one."""
        ...

    def save(self, job: ReasoningEvaluationJob) -> None:
        """Overwrite the job's state (the evaluator is its only writer)."""
        ...

    def list_by_status(
        self, status: ReasoningEvaluationJobStatus, *, older_than: datetime, limit: int
    ) -> list[ReasoningEvaluationJob]:
        """Jobs in ``status`` queued before ``older_than``, oldest first."""
        ...
