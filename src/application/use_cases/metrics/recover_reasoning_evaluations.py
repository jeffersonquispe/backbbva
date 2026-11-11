"""RecoverStaleReasoningEvaluations: the evaluator's silent safety net.

A job whose message was lost (broker restart) or whose worker died mid-run would
sit QUEUED/RUNNING forever. This sweep, run on a schedule on the evaluator's own
queue, puts such jobs back on the queue. It only reads and writes the
evaluator's jobs - never alerts or workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from src.application.ports.clock_port import Clock
from src.application.ports.reasoning_evaluation_job_dispatcher_port import (
    ReasoningEvaluationJobDispatcher,
)
from src.application.ports.reasoning_evaluation_job_port import (
    ReasoningEvaluationJobRepository,
    ReasoningEvaluationJobStatus,
)

# A healthy job leaves QUEUED within seconds and finishes within a minute or two;
# these are generous so a slow provider is not mistaken for a lost job.
QUEUED_STALE_AFTER = timedelta(minutes=10)
RUNNING_STALE_AFTER = timedelta(minutes=15)
# Stop retrying a job that keeps dying (poison input): it becomes FAILED.
MAX_ATTEMPTS = 6


@dataclass(frozen=True)
class RecoverReasoningEvaluationsOutput:
    requeued: int
    failed: int


class RecoverStaleReasoningEvaluations:
    def __init__(
        self,
        jobs: ReasoningEvaluationJobRepository,
        dispatcher: ReasoningEvaluationJobDispatcher,
        clock: Clock,
    ) -> None:
        self._jobs = jobs
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(self, limit: int = 100) -> RecoverReasoningEvaluationsOutput:
        now = self._clock.now()
        requeued = failed = 0
        stale = [
            *self._jobs.list_by_status(
                ReasoningEvaluationJobStatus.QUEUED,
                older_than=now - QUEUED_STALE_AFTER,
                limit=limit,
            ),
            *(
                job
                for job in self._jobs.list_by_status(
                    ReasoningEvaluationJobStatus.RUNNING,
                    older_than=now - RUNNING_STALE_AFTER,
                    limit=limit,
                )
                # queued_at is old for any long job; what matters is when it started.
                if job.started_at is None or job.started_at < now - RUNNING_STALE_AFTER
            ),
        ]
        for job in stale:
            if job.attempts >= MAX_ATTEMPTS:
                job.status = ReasoningEvaluationJobStatus.FAILED
                job.error_code = "TOO_MANY_ATTEMPTS"
                job.finished_at = now
                self._jobs.save(job)
                failed += 1
                continue
            job.status = ReasoningEvaluationJobStatus.QUEUED
            self._jobs.save(job)
            self._dispatcher.enqueue(job.alert_id, job.workflow_execution_id)
            requeued += 1
        return RecoverReasoningEvaluationsOutput(requeued=requeued, failed=failed)
