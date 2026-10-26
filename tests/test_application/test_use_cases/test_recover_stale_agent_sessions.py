"""Recovery of an orchestrator that died after its run finished (H9 failure)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionStatus,
)
from src.application.ports.clock_port import Clock
from src.application.use_cases.agent.recover_stale_agent_runs import (
    RecoverStaleAgentRunsUseCase,
)
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
)

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class InMemorySessions:
    def __init__(self, *sessions: AgentSession) -> None:
        self.items = {item.session_id: item for item in sessions}

    def get(self, session_id):
        return self.items.get(session_id)

    def list_by_status(self, status, limit=50):
        return [item for item in self.items.values() if item.status == status][:limit]

    def update(self, session, expected_rev):
        current = self.items[session.session_id]
        if expected_rev != current.rev:
            raise AssertionError("stale revision")
        self.items[session.session_id] = replace(session, rev=expected_rev + 1)
        return self.items[session.session_id]


class InMemoryIterations:
    def __init__(self, *items: AgentIteration) -> None:
        self.items = {(item.session_id, item.number): item for item in items}

    def list_for_session(self, session_id, limit=50):
        return [item for (owner, _), item in self.items.items() if owner == session_id][
            :limit
        ]

    def get(self, session_id, number):
        return self.items.get((session_id, number))

    def update(self, item):
        self.items[(item.session_id, item.number)] = item
        return item


class InMemoryRuns:
    """Only RUNNING runs with an expired lease are stale; finished runs never are."""

    def __init__(self, *runs) -> None:
        self.items = {run.run_id: run for run in runs}

    def list_stale(self, now, limit=100):
        return []

    def get(self, run_id):
        return self.items.get(run_id)

    def update(self, item):
        return item


class InMemoryExperiments:
    def __init__(self, *items: AgentExperiment) -> None:
        self.items = {(item.session_id, item.experiment_id): item for item in items}

    def list_for_session(self, session_id, limit=50):
        return [item for (owner, _), item in self.items.items() if owner == session_id][
            :limit
        ]

    def update(self, experiment, *, expected_status):
        key = (experiment.session_id, experiment.experiment_id)
        if self.items[key].status.value != expected_status:
            raise AssertionError("experiment changed concurrently")
        self.items[key] = experiment
        return experiment


def _session(**changes) -> AgentSession:
    return replace(
        AgentSession(
            session_id="s1",
            mode="optimization",
            status=AgentSessionStatus.ACTIVE,
            owner_id="u1",
            created_at=NOW,
            updated_at=NOW,
            budget_limits={"tokens": 10, "seconds": 10},
            lease_owner="dead-worker",
            lease_expires_at=NOW,
            rev=1,
        ),
        **changes,
    )


def _iteration(status: AgentIterationStatus) -> AgentIteration:
    return AgentIteration(
        session_id="s1",
        number=1,
        status=status,
        started_at=NOW,
        run_ids=("r1",),
    )


def _experiment(status: AgentExperimentStatus) -> AgentExperiment:
    return AgentExperiment(
        session_id="s1",
        experiment_id="e1",
        iteration_number=1,
        kind=AgentExperimentKind.ISOLATED,
        status=status,
        components=(),
        objective_id="o1",
        objective_version=1,
        created_at=NOW,
    )


def _recovery(sessions, iterations, experiments) -> RecoverStaleAgentRunsUseCase:
    return RecoverStaleAgentRunsUseCase(
        sessions=sessions,
        iterations=iterations,
        runs=InMemoryRuns(),
        experiments=experiments,
        clock=FixedClock(),
    )


def test_dead_orchestrator_with_finished_run_closes_iteration_and_experiment() -> None:
    sessions = InMemorySessions(_session())
    iterations = InMemoryIterations(_iteration(AgentIterationStatus.RUNNING))
    experiments = InMemoryExperiments(_experiment(AgentExperimentStatus.RUNNING))

    recovered = _recovery(sessions, iterations, experiments).execute()

    assert recovered == ["s1"]
    assert iterations.items[("s1", 1)].status == AgentIterationStatus.FAILED
    assert iterations.items[("s1", 1)].decision["error_code"] == "WORKER_LEASE_EXPIRED"
    closed = experiments.items[("s1", "e1")]
    assert closed.status == AgentExperimentStatus.FAILED
    assert closed.error_code == "WORKER_LEASE_EXPIRED"
    assert closed.completed_at == NOW
    assert sessions.items["s1"].lease_owner is None
    assert sessions.items["s1"].lease_expires_at is None


def test_live_lease_is_never_swept() -> None:
    later = datetime(2026, 10, 26, 12, 5, tzinfo=UTC)
    sessions = InMemorySessions(_session(lease_expires_at=later))
    iterations = InMemoryIterations(_iteration(AgentIterationStatus.RUNNING))
    experiments = InMemoryExperiments(_experiment(AgentExperimentStatus.RUNNING))

    recovered = _recovery(sessions, iterations, experiments).execute()

    assert recovered == []
    assert iterations.items[("s1", 1)].status == AgentIterationStatus.RUNNING
    assert experiments.items[("s1", "e1")].status == AgentExperimentStatus.RUNNING
    assert sessions.items["s1"].lease_owner == "dead-worker"


def test_finished_work_is_left_untouched_when_only_the_lease_expired() -> None:
    sessions = InMemorySessions(_session())
    iterations = InMemoryIterations(_iteration(AgentIterationStatus.SUCCEEDED))
    experiments = InMemoryExperiments(_experiment(AgentExperimentStatus.SUCCEEDED))

    recovered = _recovery(sessions, iterations, experiments).execute()

    assert recovered == ["s1"]
    assert iterations.items[("s1", 1)].status == AgentIterationStatus.SUCCEEDED
    assert experiments.items[("s1", "e1")].status == AgentExperimentStatus.SUCCEEDED


def test_paused_session_is_not_requeued() -> None:
    sessions = InMemorySessions(_session(status=AgentSessionStatus.PAUSED))
    iterations = InMemoryIterations()
    experiments = InMemoryExperiments()

    recovered = _recovery(sessions, iterations, experiments).execute()

    assert recovered == []
    assert sessions.items["s1"].status == AgentSessionStatus.PAUSED


def test_recovery_twice_is_idempotent() -> None:
    sessions = InMemorySessions(_session())
    iterations = InMemoryIterations(_iteration(AgentIterationStatus.RUNNING))
    experiments = InMemoryExperiments(_experiment(AgentExperimentStatus.RUNNING))
    recovery = _recovery(sessions, iterations, experiments)

    recovery.execute()
    second = recovery.execute()

    assert second == []
    assert experiments.items[("s1", "e1")].status == AgentExperimentStatus.FAILED


def test_recovery_leaves_a_visible_timeline_event() -> None:
    from src.application.use_cases.agent.agent_timeline import AgentTimeline
    from src.domain.agents.event import AgentEvent

    class Events:
        def __init__(self) -> None:
            self.items: list[AgentEvent] = []

        def append(self, event):
            self.items.append(event)
            return event

    class Ids:
        def new_id(self):
            return "00000000-0000-0000-0000-000000000001"

    events = Events()
    recovery = RecoverStaleAgentRunsUseCase(
        sessions=InMemorySessions(_session()),
        iterations=InMemoryIterations(_iteration(AgentIterationStatus.RUNNING)),
        runs=InMemoryRuns(),
        experiments=InMemoryExperiments(_experiment(AgentExperimentStatus.RUNNING)),
        clock=FixedClock(),
        timeline=AgentTimeline(events=events, clock=FixedClock(), ids=Ids()),
    )

    recovery.execute()

    assert [(item.kind.value, item.reason_code) for item in events.items] == [
        ("recovery", "WORKER_LEASE_EXPIRED")
    ]


def test_parallel_candidate_with_a_live_run_lease_is_not_orphaned() -> None:
    from datetime import timedelta

    from src.application.ports.agent_run_port import AgentRun, AgentRunStatus

    live = AgentRun(
        run_id="r1",
        session_id="s1",
        iteration_number=1,
        subagent="xgboost",
        status=AgentRunStatus.RUNNING,
        prompt_ref={},
        created_at=NOW,
        lease_expires_at=NOW + timedelta(seconds=60),
    )
    sessions = InMemorySessions(_session())
    iterations = InMemoryIterations(_iteration(AgentIterationStatus.RUNNING))
    experiments = InMemoryExperiments(_experiment(AgentExperimentStatus.RUNNING))
    recovery = RecoverStaleAgentRunsUseCase(
        sessions=sessions,
        iterations=iterations,
        runs=InMemoryRuns(live),
        experiments=experiments,
        clock=FixedClock(),
    )

    recovery.execute()

    assert iterations.items[("s1", 1)].status == AgentIterationStatus.RUNNING
    assert experiments.items[("s1", "e1")].status == AgentExperimentStatus.RUNNING
