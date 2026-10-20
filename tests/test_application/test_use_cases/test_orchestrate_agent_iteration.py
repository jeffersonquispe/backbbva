from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from src.application.ports.agent_budget_ledger_port import AgentBudgetEntry
from src.application.ports.agent_hypothesis_port import (
    AgentHypothesis,
    AgentHypothesisStatus,
)
from src.application.ports.agent_insight_port import (
    AgentInsight,
    AgentInsightKind,
    AgentInsightStatus,
)
from src.application.ports.agent_iteration_port import (
    AgentIteration,
    AgentIterationStatus,
)
from src.application.ports.agent_link_port import AgentLink
from src.application.ports.agent_package_port import AgentPackage
from src.application.ports.agent_run_port import AgentRun, AgentRunStatus
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionStatus,
)
from src.application.ports.agent_subagent_port import (
    AgentSubagent,
    AgentSubagentInput,
    AgentSubagentOutput,
)
from src.application.ports.agent_verification_port import AgentVerification
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.use_cases.agent.manage_agent_session import (
    ManageAgentSessionUseCase,
)
from src.application.use_cases.agent.orchestrate_agent_iteration import (
    OrchestrateAgentIterationUseCase,
)
from src.application.use_cases.agent.recover_stale_agent_runs import (
    RecoverStaleAgentRunsUseCase,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)


class InMemorySessions:
    def __init__(self, session: AgentSession) -> None:
        self.session = session

    def get(self, session_id):
        return self.session if self.session.session_id == session_id else None

    def list_by_status(self, status, limit=50):
        return [self.session] if self.session.status == status else []

    def acquire_lease(self, session_id, owner, now, expires_at):
        if self.session.lease_expires_at and self.session.lease_expires_at > now:
            return None
        self.session = replace(
            self.session,
            lease_owner=owner,
            lease_expires_at=expires_at,
            rev=self.session.rev + 1,
        )
        return self.session

    def update(self, session, expected_rev):
        if expected_rev != self.session.rev:
            raise AssertionError("stale revision")
        self.session = replace(session, rev=expected_rev + 1)
        return self.session


class InMemoryIterations:
    def __init__(self) -> None:
        self.items: dict[int, AgentIteration] = {}

    def list_for_session(self, session_id, limit=50):
        return list(self.items.values())[:limit]

    def create(self, item):
        self.items[item.number] = item
        return item

    def update(self, item):
        self.items[item.number] = item
        return item

    def get(self, session_id, number):
        return self.items.get(number)


class InMemoryRuns:
    def __init__(self) -> None:
        self.items: dict[str, AgentRun] = {}
        self.stale: list[AgentRun] = []

    def create(self, item):
        self.items[item.run_id] = item
        return item

    def update(self, item):
        self.items[item.run_id] = item
        return item

    def get(self, run_id):
        return self.items.get(run_id)

    def list_stale(self, now, limit=100):
        return self.stale[:limit]

    def list_active(self, now, limit=100):
        return []


class InMemoryBudget:
    def __init__(self) -> None:
        self.spent: dict[str, int] = {}
        self.entries: list[AgentBudgetEntry] = []

    def reserve(self, session_id, resource, amount, limit):
        current = self.spent.get(resource, 0)
        if current + amount > limit:
            return False
        self.spent[resource] = current + amount
        return True

    def append(self, entry):
        self.entries.append(entry)
        return entry

    def list_for_session(self, session_id, limit=100):
        return self.entries[:limit]


class InMemoryPackages:
    def __init__(self) -> None:
        self.items: dict[str, AgentPackage] = {}

    def create(self, item):
        self.items[item.package_id] = item
        return item

    def list_for_session(self, session_id, limit=50):
        return list(self.items.values())[:limit]

    def get(self, package_id):
        return self.items.get(package_id)

    def update(self, package, expected_rev):
        self.items[package.package_id] = package
        return package


class InMemoryVerifications:
    def __init__(self) -> None:
        self.items: dict[str, AgentVerification] = {}

    def create(self, item):
        self.items[item.verification_id] = item
        return item

    def list_for_subject(self, subject_id):
        return [item for item in self.items.values() if item.subject_id == subject_id]


class InMemoryHypotheses:
    def __init__(self):
        self.items: dict[str, AgentHypothesis] = {}

    def create(self, item):
        self.items[item.hypothesis_id] = item
        return item

    def list_for_session(self, session_id, limit=100):
        return [item for item in self.items.values() if item.session_id == session_id][:limit]

    def update(self, item, expected_rev):
        self.items[item.hypothesis_id] = replace(item, rev=expected_rev + 1)
        return self.items[item.hypothesis_id]


class InMemoryInsights:
    def __init__(self, items):
        self.items = {item.insight_id: item for item in items}

    def list_for_session(self, session_id, status=None, limit=100):
        return [
            item
            for item in self.items.values()
            if item.session_id == session_id and (status is None or item.status == status)
        ][:limit]

    def get(self, session_id, insight_id):
        item = self.items.get(insight_id)
        return item if item and item.session_id == session_id else None

    def update(self, item, expected_rev):
        self.items[item.insight_id] = replace(item, rev=expected_rev + 1)
        return self.items[item.insight_id]


class InMemoryLinks:
    def __init__(self):
        self.items: list[AgentLink] = []

    def create_once(self, link):
        self.items.append(link)
        return link

    def list_from(self, session_id, source_type, source_id):
        return [item for item in self.items if item.source_id == source_id]

    def list_to(self, target_type, target_id):
        return [item for item in self.items if item.target_id == target_id]


class InMemorySettings(AssistantOptimizerSettingsPort):
    def __init__(self, settings: AssistantOptimizerSettings) -> None:
        self.settings = settings
        self.read_count = 0

    def get(self) -> AssistantOptimizerSettings:
        self.read_count += 1
        return self.settings

    def update(self, settings: AssistantOptimizerSettings) -> AssistantOptimizerSettings:
        self.settings = settings
        return settings


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class SequenceIdGenerator(IdGenerator):
    def __init__(self) -> None:
        self.sequence = 0

    def new_id(self) -> UUID:
        self.sequence += 1
        return UUID(int=self.sequence)


class InMemoryStubSubagent:
    name = "stub"

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        return AgentSubagentOutput(
            subagent=self.name,
            contribution={"result": "ready"},
            verification_status="PASSED",
            safe_metrics={"checks": 1},
        )


class MetricSubagent:
    name = "stub"

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        return AgentSubagentOutput(
            subagent=self.name,
            verification_status="PASSED",
            safe_metrics={"precision": 0.95, "recall": 0.6},
        )


def _use_case(
    session,
    settings,
    subagent: AgentSubagent | None = None,
    sessions_repository: InMemorySessions | None = None,
    hypotheses=None,
    insights=None,
    links=None,
):
    repositories = {
        "sessions": sessions_repository or InMemorySessions(session),
        "iterations": InMemoryIterations(),
        "runs": InMemoryRuns(),
        "budget": InMemoryBudget(),
        "packages": InMemoryPackages(),
        "verifications": InMemoryVerifications(),
    }
    use_case = OrchestrateAgentIterationUseCase(
        **repositories,
        settings=settings,
        subagent=subagent or InMemoryStubSubagent(),
        clock=FixedClock(),
        id_generator=SequenceIdGenerator(),
        hypotheses=hypotheses,
        insights=insights,
        links=links,
    )
    return use_case, repositories


def _session(mode: str = "assistant") -> AgentSession:
    return AgentSession(
        session_id="s1",
        mode=mode,
        status=AgentSessionStatus.ACTIVE,
        owner_id="u1",
        created_at=NOW,
        updated_at=NOW,
        budget_limits={"tokens": 10, "seconds": 10},
    )


def test_tick_reads_settings_and_pauses_when_optimizer_kill_switch_is_off() -> None:
    settings = InMemorySettings(AssistantOptimizerSettings(optimizer_enabled=False))
    use_case, repositories = _use_case(_session("optimization"), settings)

    result = use_case.execute("s1")

    assert result == "paused_by_kill_switch"
    assert repositories["sessions"].session.status == AgentSessionStatus.PAUSED
    assert settings.read_count == 1
    assert repositories["runs"].items == {}


def test_tick_persists_one_stub_iteration_and_clears_lease() -> None:
    settings = InMemorySettings(AssistantOptimizerSettings())
    use_case, repositories = _use_case(_session(), settings)

    result = use_case.execute("s1")

    assert result == "iteration_completed"
    assert settings.read_count == 1
    assert repositories["budget"].spent == {
        "tokens": 1,
        "usd_micros": 1,
        "seconds": 1,
    }
    assert len(repositories["runs"].items) == 1
    assert len(repositories["packages"].items) == 1
    assert len(repositories["verifications"].items) == 1
    assert list(repositories["iterations"].items.values())[0].status == (
        AgentIterationStatus.SUCCEEDED
    )
    session = repositories["sessions"].session
    assert session.status == AgentSessionStatus.PAUSED
    assert session.lease_owner is None
    assert session.lease_expires_at is None


def test_optimizer_stops_deterministically_after_configured_stagnation() -> None:
    settings = InMemorySettings(
        AssistantOptimizerSettings(
            optimizer_enabled=True,
            optimizer_iterations_without_improvement=2,
        )
    )
    session = _session("optimization")
    use_case, repositories = _use_case(session, settings, subagent=MetricSubagent())

    assert use_case.execute("s1") == "iteration_completed"
    repositories["sessions"].session = replace(
        repositories["sessions"].session,
        status=AgentSessionStatus.ACTIVE,
        rev=repositories["sessions"].session.rev + 1,
    )
    assert use_case.execute("s1") == "iteration_completed"
    repositories["sessions"].session = replace(
        repositories["sessions"].session,
        status=AgentSessionStatus.ACTIVE,
        rev=repositories["sessions"].session.rev + 1,
    )
    assert use_case.execute("s1") == "stopped_by_stagnation"

    assert repositories["sessions"].session.status == AgentSessionStatus.STOPPED
    assert len(repositories["iterations"].items) == 3
    assert all(item.package_id is None for item in repositories["iterations"].items.values())
    decision = repositories["iterations"].items[3].decision
    assert decision["action"] == "stop"
    assert decision["score"] == 0.6
    assert decision["improved"] is False
    assert decision["stale_iterations"] == 2
    assert decision["reason"] == "stagnation"


def test_active_insight_is_ranked_evaluated_and_linked_to_verification() -> None:
    insight = AgentInsight(
        session_id="s1",
        insight_id="directive-1",
        kind=AgentInsightKind.DIRECTIVE,
        statement="Mejorar recall del canal digital sin bajar precisión.",
        scope={"area": "model"},
        status=AgentInsightStatus.ACTIVE,
        proposed_by="user",
        author_id="u1",
        source_message_id="m1",
        created_at=NOW,
        updated_at=NOW,
    )
    hypotheses, insights, links = (
        InMemoryHypotheses(),
        InMemoryInsights([insight]),
        InMemoryLinks(),
    )
    use_case, repositories = _use_case(
        _session("optimization"),
        InMemorySettings(AssistantOptimizerSettings(optimizer_enabled=True)),
        subagent=MetricSubagent(),
        hypotheses=hypotheses,
        insights=insights,
        links=links,
    )

    assert use_case.execute("s1") == "iteration_completed"

    hypothesis = next(iter(hypotheses.items.values()))
    assert hypothesis.status == AgentHypothesisStatus.VALIDATED
    assert hypothesis.priority == 100
    assert hypothesis.evidence_outcome == "VALIDATED"
    assert insights.items["directive-1"].status == AgentInsightStatus.APPLIED
    verification_id = next(iter(repositories["verifications"].items))
    assert links.items[0].source_id == "directive-1"
    assert links.items[0].relation == "supported_by"
    assert links.items[0].target_id == verification_id


def test_cancelled_session_is_not_enqueued_for_another_tick() -> None:
    session_repository = InMemorySessions(_session())
    manager = ManageAgentSessionUseCase(session_repository, FixedClock())
    cancelled = manager.cancel("s1", "u1")
    settings = InMemorySettings(AssistantOptimizerSettings())
    use_case, repositories = _use_case(cancelled, settings)

    result = use_case.execute("s1")

    assert result == "not_active"
    assert repositories["runs"].items == {}
    assert settings.read_count == 1


class CancellingSubagent:
    name = "stub"

    def __init__(self, sessions: InMemorySessions) -> None:
        self.sessions = sessions

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        ManageAgentSessionUseCase(self.sessions, FixedClock()).cancel(
            request.session_id, "u1"
        )
        return AgentSubagentOutput(
            subagent=self.name,
            contribution={"must_not_be_saved": True},
            verification_status="PASSED",
        )


def test_cancel_during_subagent_execution_discards_output_and_clears_lease() -> None:
    settings = InMemorySettings(AssistantOptimizerSettings())
    session = _session()
    sessions = InMemorySessions(session)
    use_case, repositories = _use_case(
        session,
        settings,
        subagent=CancellingSubagent(sessions),
        sessions_repository=sessions,
    )

    result = use_case.execute("s1")

    assert result == "cancelled"
    assert sessions.session.status == AgentSessionStatus.CANCELLED
    assert sessions.session.lease_owner is None
    assert repositories["packages"].items == {}
    assert next(iter(repositories["runs"].items.values())).status == (
        AgentRunStatus.CANCELLED
    )
    assert next(iter(repositories["iterations"].items.values())).decision == {
        "action": "cancelled"
    }


def test_stale_run_recovery_marks_failure_releases_lease_and_returns_session() -> None:
    session = replace(
        _session(),
        lease_owner="dead-worker",
        lease_expires_at=NOW,
        rev=1,
    )
    repositories = {
        "sessions": InMemorySessions(session),
        "iterations": InMemoryIterations(),
        "runs": InMemoryRuns(),
    }
    running = AgentRun(
        run_id="r1",
        session_id="s1",
        iteration_number=1,
        subagent="stub",
        status=AgentRunStatus.RUNNING,
        prompt_ref={},
        created_at=NOW,
        lease_expires_at=NOW,
    )
    repositories["runs"].items[running.run_id] = running
    repositories["runs"].stale = [running]
    repositories["iterations"].items[1] = AgentIteration(
        session_id="s1",
        number=1,
        status=AgentIterationStatus.RUNNING,
        started_at=NOW,
        run_ids=(running.run_id,),
    )
    recovery = RecoverStaleAgentRunsUseCase(
        sessions=repositories["sessions"],
        iterations=repositories["iterations"],
        runs=repositories["runs"],
        clock=FixedClock(),
    )

    recovered = recovery.execute()

    assert recovered == ["s1"]
    assert repositories["runs"].items["r1"].status == AgentRunStatus.FAILED
    assert repositories["runs"].items["r1"].error_code == "WORKER_LEASE_EXPIRED"
    assert repositories["iterations"].items[1].status == AgentIterationStatus.FAILED
    assert repositories["sessions"].session.lease_owner is None
    assert repositories["sessions"].session.lease_expires_at is None


def test_stale_cancelled_session_has_lease_cleared_without_requeue() -> None:
    session = replace(
        _session(),
        status=AgentSessionStatus.CANCELLED,
        lease_owner="dead-worker",
        lease_expires_at=NOW,
        rev=1,
    )
    sessions = InMemorySessions(session)
    runs = InMemoryRuns()
    stale_run = AgentRun(
        run_id="cancelled-run",
        session_id="s1",
        iteration_number=1,
        subagent="stub",
        status=AgentRunStatus.RUNNING,
        prompt_ref={},
        created_at=NOW,
        lease_expires_at=NOW,
    )
    runs.stale = [stale_run]
    runs.items[stale_run.run_id] = stale_run
    recovery = RecoverStaleAgentRunsUseCase(
        sessions=sessions,
        iterations=InMemoryIterations(),
        runs=runs,
        clock=FixedClock(),
    )

    recovered = recovery.execute()

    assert recovered == []
    assert sessions.session.status == AgentSessionStatus.CANCELLED
    assert sessions.session.lease_owner is None
    assert sessions.session.lease_expires_at is None
