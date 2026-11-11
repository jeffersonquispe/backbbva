"""The evaluator as its own flow: intake (sampling, origin, job), the job's state
while judging, and the silent recovery of lost jobs. None of it ever writes to
the alert: the in-memory alert repository below has no write method at all."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from src.application.ports.reasoning_evaluation_job_port import (
    ReasoningEvaluationJob,
    ReasoningEvaluationJobStatus,
)
from src.application.use_cases.metrics.read_reasoning_evaluations import (
    ReasoningEvaluationAlertNotFoundError,
)
from src.application.use_cases.metrics.recover_reasoning_evaluations import (
    MAX_ATTEMPTS,
    QUEUED_STALE_AFTER,
    RUNNING_STALE_AFTER,
    RecoverStaleReasoningEvaluations,
)
from src.application.use_cases.metrics.request_reasoning_evaluation import (
    ReasoningEvaluationNotReadyError,
    RequestOutcome,
    RequestReasoningEvaluation,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
Status = ReasoningEvaluationJobStatus


class MutableClock:
    def __init__(self) -> None:
        self.current = NOW

    def now(self) -> datetime:
        return self.current


class ReadOnlyAlerts:
    """Only `get`: the evaluator must never write an alert."""

    def __init__(self) -> None:
        self.rows: dict[UUID, object] = {}

    def add(
        self, origin: str | None = "production", workflow: UUID | None = None
    ) -> UUID:
        alert_id = uuid4()
        metrics = SimpleNamespace(origin=origin) if origin is not None else None
        self.rows[alert_id] = SimpleNamespace(
            metrics=metrics, workflow_execution_id=workflow or uuid4()
        )
        return alert_id

    def get(self, alert_id: UUID):
        return self.rows.get(alert_id)


class InMemoryJobs:
    def __init__(self) -> None:
        self.rows: dict[UUID, ReasoningEvaluationJob] = {}

    def create_if_absent(self, job):
        if job.alert_id in self.rows:
            return False
        self.rows[job.alert_id] = job
        return True

    def requeue(self, job):
        current = self.rows.get(job.alert_id)
        if current is None or current.status not in (Status.FAILED, Status.INVALID):
            return False
        self.rows[job.alert_id] = job
        return True

    def get(self, alert_id):
        return self.rows.get(alert_id)

    def save(self, job):
        self.rows[job.alert_id] = job

    def list_by_status(self, status, *, older_than, limit):
        found = [
            j
            for j in self.rows.values()
            if j.status == status and j.queued_at < older_than
        ]
        return sorted(found, key=lambda j: j.queued_at)[:limit]


class RecordingJobDispatcher:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    def enqueue(self, alert_id, workflow_execution_id) -> None:
        self.calls.append((alert_id, workflow_execution_id))


class InMemoryOperationalSettings:
    def __init__(self, rate: float) -> None:
        self.rate = rate

    def get(self):
        return SimpleNamespace(reasoning_evaluation_sample_rate=self.rate)


def _flow(rate: float = 1.0):
    alerts, jobs, dispatcher = (
        ReadOnlyAlerts(),
        InMemoryJobs(),
        RecordingJobDispatcher(),
    )
    request = RequestReasoningEvaluation(
        jobs, alerts, InMemoryOperationalSettings(rate), dispatcher, MutableClock()
    )
    return request, alerts, jobs, dispatcher


def test_a_sampled_alert_opens_a_queued_job_and_goes_to_the_evaluators_queue() -> None:
    request, alerts, jobs, dispatcher = _flow(rate=1.0)
    alert_id = alerts.add()

    out = request.execute(alert_id)

    assert out.outcome == RequestOutcome.QUEUED
    job = jobs.get(alert_id)
    assert (job.status, job.requested_by, job.queued_at) == (
        Status.QUEUED,
        "workflow",
        NOW,
    )
    assert dispatcher.calls == [(alert_id, job.workflow_execution_id)]


def test_an_alert_that_is_not_sampled_gets_no_job_and_nothing_is_queued() -> None:
    request, alerts, jobs, dispatcher = _flow(rate=0.0)
    alert_id = alerts.add()

    out = request.execute(alert_id)

    assert out.outcome == RequestOutcome.NOT_SAMPLED and out.job is None
    assert jobs.rows == {} and dispatcher.calls == []


@pytest.mark.parametrize("origin", ["test_run", "optimizer_evaluation"])
def test_test_and_optimizer_runs_are_never_judged_not_even_when_asked(origin) -> None:
    request, alerts, jobs, dispatcher = _flow(rate=1.0)
    alert_id = alerts.add(origin=origin)

    for forced in (False, True):
        assert (
            request.execute(alert_id, forced=forced).outcome
            == RequestOutcome.NOT_APPLICABLE
        )
    assert jobs.rows == {} and dispatcher.calls == []


def test_announcing_twice_does_not_queue_twice() -> None:
    request, alerts, _, dispatcher = _flow()
    alert_id = alerts.add()

    first = request.execute(alert_id)
    second = request.execute(alert_id)

    assert (first.outcome, second.outcome) == (
        RequestOutcome.QUEUED,
        RequestOutcome.EXISTING,
    )
    assert len(dispatcher.calls) == 1


def test_a_person_can_force_an_unsampled_alert_and_requeue_a_failed_one() -> None:
    request, alerts, jobs, dispatcher = _flow(rate=0.0)
    alert_id = alerts.add()

    forced = request.execute(alert_id, forced=True)
    assert forced.outcome == RequestOutcome.QUEUED
    assert jobs.get(alert_id).requested_by == "manual"

    jobs.get(alert_id).status = Status.FAILED
    again = request.execute(alert_id, forced=True)
    assert again.outcome == RequestOutcome.QUEUED and len(dispatcher.calls) == 2

    # A finished or running job is returned as is, never started over.
    jobs.get(alert_id).status = Status.EVALUATED
    assert request.execute(alert_id, forced=True).outcome == RequestOutcome.EXISTING
    assert len(dispatcher.calls) == 2


def test_an_automatic_announcement_does_not_retry_a_failed_job() -> None:
    request, alerts, jobs, dispatcher = _flow()
    alert_id = alerts.add()
    request.execute(alert_id)
    jobs.get(alert_id).status = Status.FAILED

    assert request.execute(alert_id).outcome == RequestOutcome.EXISTING
    assert len(dispatcher.calls) == 1


def test_unknown_alert_and_alert_without_a_run_are_reported() -> None:
    request, alerts, _, _ = _flow()
    with pytest.raises(ReasoningEvaluationAlertNotFoundError):
        request.execute(uuid4())
    alert_id = alerts.add()
    alerts.rows[alert_id].workflow_execution_id = None
    with pytest.raises(ReasoningEvaluationNotReadyError):
        request.execute(alert_id, forced=True)


def _stale_job(jobs: InMemoryJobs, status, *, queued_ago, started_ago=None, attempts=1):
    job = ReasoningEvaluationJob(
        alert_id=uuid4(),
        workflow_execution_id=uuid4(),
        status=status,
        requested_by="workflow",
        queued_at=NOW - queued_ago,
        started_at=NOW - started_ago if started_ago else None,
        attempts=attempts,
    )
    jobs.rows[job.alert_id] = job
    return job


def test_recovery_requeues_lost_and_dead_jobs_but_not_healthy_ones() -> None:
    jobs, dispatcher = InMemoryJobs(), RecordingJobDispatcher()
    lost = _stale_job(
        jobs, Status.QUEUED, queued_ago=QUEUED_STALE_AFTER + timedelta(minutes=1)
    )
    fresh = _stale_job(jobs, Status.QUEUED, queued_ago=timedelta(minutes=1))
    dead = _stale_job(
        jobs,
        Status.RUNNING,
        queued_ago=timedelta(hours=1),
        started_ago=RUNNING_STALE_AFTER + timedelta(minutes=1),
    )
    long_but_alive = _stale_job(
        jobs,
        Status.RUNNING,
        queued_ago=timedelta(hours=1),  # queued long ago, but it only just started
        started_ago=timedelta(minutes=2),
    )
    done = _stale_job(jobs, Status.EVALUATED, queued_ago=timedelta(days=1))

    out = RecoverStaleReasoningEvaluations(jobs, dispatcher, MutableClock()).execute()

    assert (out.requeued, out.failed) == (2, 0)
    assert {c[0] for c in dispatcher.calls} == {lost.alert_id, dead.alert_id}
    assert dead.status == Status.QUEUED and lost.status == Status.QUEUED
    assert long_but_alive.status == Status.RUNNING
    assert fresh.status == Status.QUEUED and done.status == Status.EVALUATED


def test_recovery_gives_up_on_a_job_that_keeps_dying() -> None:
    jobs, dispatcher = InMemoryJobs(), RecordingJobDispatcher()
    poison = _stale_job(
        jobs, Status.QUEUED, queued_ago=timedelta(hours=1), attempts=MAX_ATTEMPTS
    )

    out = RecoverStaleReasoningEvaluations(jobs, dispatcher, MutableClock()).execute()

    assert (out.requeued, out.failed) == (0, 1)
    assert poison.status == Status.FAILED and poison.error_code == "TOO_MANY_ATTEMPTS"
    assert dispatcher.calls == []


def test_job_timings_separate_waiting_from_judging() -> None:
    job = ReasoningEvaluationJob(
        alert_id=uuid4(),
        workflow_execution_id=uuid4(),
        status=Status.EVALUATED,
        requested_by="workflow",
        queued_at=NOW,
        started_at=NOW + timedelta(seconds=3),
        finished_at=NOW + timedelta(seconds=14),
        run_ms=8000,
    )

    assert (job.wait_ms, job.total_ms) == (3000, 14000)
    assert (
        ReasoningEvaluationJob(
            alert_id=uuid4(),
            workflow_execution_id=uuid4(),
            status=Status.QUEUED,
            requested_by="workflow",
            queued_at=NOW,
        ).total_ms
        is None
    )
