from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from src.application.ports.agent_hypothesis_port import (
    AgentHypothesis,
    AgentHypothesisStatus,
)
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionStatus,
)
from src.application.ports.clock_port import Clock
from src.application.use_cases.agent.get_agent_session_overview import (
    AgentOverviewNotFoundError,
    GetAgentSessionOverviewUseCase,
)
from src.domain.agents.event import AgentEvent, AgentEventKind, AgentEventOutcome

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class Sessions:
    def __init__(self, session):
        self.session = session

    def get(self, session_id):
        return self.session if session_id == self.session.session_id else None


class Iterations:
    def __init__(self, *items):
        self.items = list(items)

    def list_for_session(self, session_id, limit=50):
        return self.items


class Hypotheses:
    def __init__(self, *items):
        self.items = list(items)

    def list_for_session(self, session_id, limit=100):
        return self.items


class Experiments:
    def list_for_session(self, session_id, limit=50):
        return []


class Events:
    def __init__(self, *items):
        self.items = list(items)

    def list_latest(self, session_id, limit=20):
        return list(reversed(self.items))[:limit]


def _session(**changes) -> AgentSession:
    return replace(
        AgentSession(
            session_id="s1",
            mode="optimization",
            status=AgentSessionStatus.ACTIVE,
            owner_id="cm-1",
            created_at=NOW,
            updated_at=NOW,
        ),
        **changes,
    )


def _iteration(number, status, **decision) -> AgentIteration:
    return AgentIteration(
        session_id="s1",
        number=number,
        status=status,
        started_at=NOW,
        decision=dict(decision),
    )


def _hypothesis(status) -> AgentHypothesis:
    return AgentHypothesis(
        session_id="s1",
        hypothesis_id="h1",
        statement="x",
        scope={},
        priority=0,
        status=status,
        created_at=NOW,
        updated_at=NOW,
    )


def _overview(session, iterations=(), hypotheses=(), events=()):
    use_case = GetAgentSessionOverviewUseCase(
        sessions=Sessions(session),
        iterations=Iterations(*iterations),
        hypotheses=Hypotheses(*hypotheses),
        experiments=Experiments(),
        events=Events(*events),
        clock=FixedClock(),
    )
    return use_case.execute("s1", "cm-1")


def test_blocked_session_explains_what_the_channel_manager_must_grant() -> None:
    overview = _overview(
        _session(
            status=AgentSessionStatus.WAITING_USER,
            block={"code": "BUDGET_EXHAUSTED"},
        )
    )

    verdict = overview.verdict
    assert verdict.state == "blocked"
    assert verdict.title == "Presupuesto agotado"
    assert verdict.approval == "budget"
    assert "Aprueba" in (verdict.action or "")


def test_dead_worker_is_reported_as_stalled_not_running() -> None:
    expired = NOW - timedelta(minutes=5)
    overview = _overview(
        _session(lease_owner="w", lease_expires_at=expired),
        iterations=[_iteration(1, AgentIterationStatus.RUNNING)],
    )

    assert overview.health.stalled is True
    assert overview.health.lease == "EXPIRED"
    assert overview.verdict.state == "stalled"
    assert overview.verdict.retryable is True


def test_live_lease_is_running() -> None:
    overview = _overview(
        _session(lease_owner="w", lease_expires_at=NOW + timedelta(seconds=60)),
        iterations=[_iteration(2, AgentIterationStatus.RUNNING)],
    )

    assert overview.health.lease == "ACTIVE"
    assert overview.verdict.state == "running"
    assert "iteración 2" in overview.verdict.title


def test_failed_iteration_shows_catalogue_reason_and_action() -> None:
    overview = _overview(
        _session(),
        iterations=[
            _iteration(
                1, AgentIterationStatus.FAILED, failure_code="MODEL_TRAINING_FAILED"
            )
        ],
    )

    assert overview.verdict.state == "failing"
    assert "Falló el entrenamiento" in overview.verdict.title
    assert overview.verdict.retryable is True
    assert overview.verdict.action


def test_finished_without_a_validated_hypothesis_is_inconclusive() -> None:
    overview = _overview(
        _session(status=AgentSessionStatus.STOPPED),
        iterations=[_iteration(1, AgentIterationStatus.SUCCEEDED)],
        hypotheses=[_hypothesis(AgentHypothesisStatus.REFUTED)],
    )

    assert overview.verdict.state == "inconclusive"
    assert overview.hypotheses == {"REFUTED": 1}


def test_finished_with_a_validated_hypothesis_is_a_success() -> None:
    overview = _overview(
        _session(status=AgentSessionStatus.COMPLETED),
        hypotheses=[_hypothesis(AgentHypothesisStatus.VALIDATED)],
    )

    assert overview.verdict.state == "completed"


def test_counts_and_last_event_age() -> None:
    event = AgentEvent(
        session_id="s1",
        seq=7,
        event_id="e",
        occurred_at=NOW - timedelta(seconds=42),
        kind=AgentEventKind.ITERATION,
        outcome=AgentEventOutcome.STARTED,
        summary="x",
    )
    overview = _overview(
        _session(),
        iterations=[
            _iteration(1, AgentIterationStatus.SUCCEEDED),
            _iteration(2, AgentIterationStatus.FAILED),
        ],
        events=[event],
    )

    assert overview.iterations == {"SUCCEEDED": 1, "FAILED": 1}
    assert overview.events_total == 7
    assert overview.health.seconds_since_last_event == 42


def test_other_owners_cannot_read_the_overview() -> None:
    use_case = GetAgentSessionOverviewUseCase(
        sessions=Sessions(_session()),
        iterations=Iterations(),
        hypotheses=Hypotheses(),
        experiments=Experiments(),
        events=Events(),
        clock=FixedClock(),
    )

    with pytest.raises(AgentOverviewNotFoundError):
        use_case.execute("s1", "someone-else")


def test_parallel_candidates_are_reported_together() -> None:
    overview = _overview(
        _session(),
        iterations=[
            _iteration(1, AgentIterationStatus.RUNNING),
            _iteration(2, AgentIterationStatus.RUNNING),
            _iteration(3, AgentIterationStatus.RUNNING),
        ],
    )

    assert overview.verdict.state == "running"
    assert overview.verdict.title == "Trabajando en 3 candidatos en paralelo"
