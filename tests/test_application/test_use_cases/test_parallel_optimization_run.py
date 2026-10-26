"""Parallel optimizer candidates inside one OptimizationRun."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from src.application.ports.agent_candidate_dispatcher_port import (
    AgentCandidateDispatcher,
)
from src.application.ports.agent_hypothesis_port import AgentHypothesisStatus
from src.application.ports.agent_iteration_port import AgentIterationStatus
from src.application.ports.agent_run_port import AgentRunStatus
from src.application.ports.agent_session_port import (
    AgentSession,
    AgentSessionStatus,
)
from src.application.ports.agent_subagent_port import (
    AgentSubagentInput,
    AgentSubagentOutput,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.use_cases.agent.agent_timeline import AgentTimeline
from src.application.use_cases.agent.orchestrate_agent_iteration import (
    OrchestrateAgentIterationUseCase,
)
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.domain.agents.optimization_run import (
    OptimizationRunConflictError,
    OptimizationRunStatus,
)

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=UTC)
COMPONENTS = ("model", "configuration", "library", "vector_store")
BASE = tuple(
    ComponentVersionReference(name, f"{name}-1", "1", "a" * 64) for name in COMPONENTS
)
SPECIALIST_COMPONENT = {
    "xgboost": "model",
    "configuration": "configuration",
    "library": "library",
    "vector_store": "vector_store",
}


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class Ids(IdGenerator):
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> UUID:
        self.value += 1
        return UUID(int=self.value)


class Sessions:
    def __init__(self, session: AgentSession) -> None:
        self.session = session

    def get(self, session_id):
        return self.session

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
        assert expected_rev == self.session.rev, "stale revision"
        self.session = replace(session, rev=expected_rev + 1)
        return self.session


class Iterations:
    def __init__(self) -> None:
        self.items = {}

    def create(self, item):
        self.items[item.number] = item
        return item

    def update(self, item):
        self.items[item.number] = item
        return item

    def get(self, session_id, number):
        return self.items.get(number)

    def list_for_session(self, session_id, limit=50):
        return [self.items[key] for key in sorted(self.items)][:limit]


class Runs:
    def __init__(self) -> None:
        self.items = {}

    def create(self, item):
        self.items[item.run_id] = item
        return item

    def update(self, item):
        self.items[item.run_id] = item
        return item

    def get(self, run_id):
        return self.items.get(run_id)

    def list_active(self, now, limit=100):
        return [
            item
            for item in self.items.values()
            if item.status == AgentRunStatus.RUNNING
        ]

    def list_stale(self, now, limit=100):
        return []


class Budget:
    def __init__(self) -> None:
        self.entries = []

    def reserve(self, session_id, resource, amount, limit):
        return True

    def append(self, entry):
        self.entries.append(entry)
        return entry

    def list_for_session(self, session_id, limit=100):
        return self.entries


class Packages:
    def __init__(self) -> None:
        self.items = {}

    def create(self, item):
        self.items[item.package_id] = item
        return item

    def list_for_session(self, session_id, limit=50):
        return list(self.items.values())


class Verifications:
    def create(self, item):
        return item


class Hypotheses:
    def __init__(self) -> None:
        self.items = {}

    def create(self, item):
        self.items[item.hypothesis_id] = item
        return item

    def list_for_session(self, session_id, limit=100):
        return list(self.items.values())

    def update(self, item, expected_rev):
        assert self.items[item.hypothesis_id].rev == expected_rev
        self.items[item.hypothesis_id] = replace(item, rev=expected_rev + 1)
        return self.items[item.hypothesis_id]


class Experiments:
    def __init__(self) -> None:
        self.items = {}

    def create(self, item):
        self.items[item.experiment_id] = item
        return item

    def list_for_session(self, session_id, limit=50):
        return list(self.items.values())


class Runs_Tree:
    def __init__(self) -> None:
        self.root = None
        self.conflicts_to_raise = 0

    def get(self, run_id):
        return self.root

    def create_once(self, run):
        self.root = self.root or run
        return self.root

    def update(self, run, expected_rev):
        if self.conflicts_to_raise:
            self.conflicts_to_raise -= 1
            raise OptimizationRunConflictError(run.run_id)
        assert expected_rev == self.root.rev
        self.root = replace(run, rev=expected_rev + 1)
        return self.root


class Events:
    def __init__(self) -> None:
        self.items = []

    def append(self, event):
        stored = replace(event, seq=len(self.items) + 1)
        self.items.append(stored)
        return stored


class Dispatcher(AgentCandidateDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[tuple[str, int]] = []

    def dispatch(self, session_id, iteration_number):
        self.dispatched.append((session_id, iteration_number))


class Settings(AssistantOptimizerSettingsPort):
    def __init__(self, **changes) -> None:
        self.value = AssistantOptimizerSettings(optimizer_enabled=True, **changes)

    def get(self):
        return self.value

    def update(self, *args, **kwargs):
        raise NotImplementedError


class Specialist:
    """Changes its own component; recall per specialist is configurable."""

    def __init__(self, name: str, recall: float) -> None:
        self.name = name
        self.recall = recall

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        component = SPECIALIST_COMPONENT[self.name]
        stack = {pin.component: pin for pin in request.baseline_components}
        stack[component] = ComponentVersionReference(
            component, f"{component}-2", "2", "b" * 64
        )
        return AgentSubagentOutput(
            subagent=self.name,
            contribution={"changed": component},
            verification_status="PASSED",
            safe_metrics={"precision": 0.95, "recall": self.recall},
            experiment_candidate_components=tuple(
                stack[name] for name in sorted(stack)
            ),
        )


class Evaluator:
    """Stands in for EvaluateAgentExperiment and stores what it measured."""

    def __init__(
        self, experiments: Experiments, recall_by_component: dict[str, float]
    ) -> None:
        self.experiments = experiments
        self.recall_by_component = recall_by_component

    def execute(self, **kwargs):
        changed = [
            pin
            for pin in kwargs["components"]
            if pin not in kwargs["baseline_components"]
        ]
        recall = max(
            self.recall_by_component.get(pin.component, 0.6) for pin in changed
        )
        if len(changed) > 1:
            recall = (
                sum(self.recall_by_component[pin.component] for pin in changed) / 2
                + 0.05
            )
        experiment = AgentExperiment(
            session_id=kwargs["session_id"],
            experiment_id=kwargs["experiment_id"],
            iteration_number=kwargs["iteration_number"],
            kind=kwargs["kind"],
            status=AgentExperimentStatus.SUCCEEDED,
            components=kwargs["components"],
            baseline_components=kwargs["baseline_components"],
            objective_id=kwargs["objective_id"],
            objective_version=kwargs["objective_version"],
            created_at=NOW,
            global_evaluation={
                "eligible_count": 120,
                "candidate": {"precision": 0.95, "recall": recall},
                "baseline": {"precision": 0.93, "recall": 0.6},
            },
            candidate_id=kwargs["candidate_id"],
        )
        return self.experiments.create(experiment)


def _system(areas, recall_by_component=None, **settings):
    recall_by_component = recall_by_component or {
        "model": 0.7,
        "configuration": 0.68,
        "library": 0.55,
    }
    session = AgentSession(
        session_id="s1",
        mode="optimization",
        status=AgentSessionStatus.ACTIVE,
        owner_id="cm",
        created_at=NOW,
        updated_at=NOW,
        scope={"areas": areas},
        budget_limits={"tokens": 100, "usd_micros": 100, "seconds": 100},
        baseline_components=BASE,
    )
    parts = {
        "sessions": Sessions(session),
        "iterations": Iterations(),
        "runs": Runs(),
        "hypotheses": Hypotheses(),
        "experiments": Experiments(),
        "tree": Runs_Tree(),
        "events": Events(),
        "dispatcher": Dispatcher(),
    }
    use_case = OrchestrateAgentIterationUseCase(
        sessions=parts["sessions"],
        iterations=parts["iterations"],
        runs=parts["runs"],
        budget=Budget(),
        packages=Packages(),
        verifications=Verifications(),
        settings=Settings(**settings),
        subagent=Specialist("library", 0.5),
        clock=FixedClock(),
        id_generator=Ids(),
        hypotheses=parts["hypotheses"],
        specialists={
            name: Specialist(name, recall_by_component.get(component, 0.6))
            for name, component in SPECIALIST_COMPONENT.items()
        },
        experiment_evaluator=Evaluator(parts["experiments"], recall_by_component),
        timeline=AgentTimeline(events=parts["events"], clock=FixedClock(), ids=Ids()),
        experiments=parts["experiments"],
        optimization_runs=parts["tree"],
        dispatcher=parts["dispatcher"],
    )
    return use_case, parts


def _running_areas(parts) -> list[str]:
    hypotheses = parts["hypotheses"].items
    return sorted(
        hypotheses[item.decision["hypothesis_id"]].scope["area"]
        for item in parts["iterations"].items.values()
        if item.status == AgentIterationStatus.RUNNING
    )


def test_tick_dispatches_independent_candidates_in_parallel_and_frees_the_lease() -> (
    None
):
    use_case, parts = _system(["model", "configuration", "library"])

    assert use_case.execute("s1") == "dispatched_3"

    assert [number for _, number in parts["dispatcher"].dispatched] == [1, 2, 3]
    assert _running_areas(parts) == ["configuration", "library", "model"]
    assert parts["sessions"].session.lease_owner is None
    root = parts["tree"].root
    assert root.status is OptimizationRunStatus.RUNNING
    assert root.optimizer_settings["max_parallel_experiments"] == 3
    assert root.baseline_components == BASE
    assert root.events_stream == "s1"


def test_parallel_slots_respect_the_per_session_cap_and_wait_while_full() -> None:
    use_case, parts = _system(
        ["model", "configuration", "library"], optimizer_max_parallel_experiments=2
    )

    assert use_case.execute("s1") == "dispatched_2"
    assert use_case.execute("s1") == "waiting_for_experiments"
    assert len(parts["dispatcher"].dispatched) == 2


def test_global_run_cap_limits_parallelism_across_sessions() -> None:
    use_case, parts = _system(
        ["model", "configuration", "library"], optimizer_max_concurrent_runs=1
    )

    assert use_case.execute("s1") == "dispatched_1"


def test_a_candidate_job_concludes_inside_its_node_and_updates_the_winners() -> None:
    use_case, parts = _system(["model", "configuration"])
    use_case.execute("s1")
    model_iteration = next(
        number
        for number, item in parts["iterations"].items.items()
        if parts["hypotheses"].items[item.decision["hypothesis_id"]].scope["area"]
        == "model"
    )

    result = use_case.run_candidate("s1", model_iteration)

    assert result == "iteration_completed"
    iteration = parts["iterations"].items[model_iteration]
    hypothesis = parts["hypotheses"].items[iteration.decision["hypothesis_id"]]
    assert hypothesis.status is AgentHypothesisStatus.VALIDATED
    assert hypothesis.conclusion["verdict"] == "VALIDATED"
    assert hypothesis.conclusion["decision"] == "keep"
    assert round(hypothesis.conclusion["evidence"]["recall_delta"], 2) == 0.1
    experiment = next(iter(parts["experiments"].items.values()))
    assert experiment.candidate_id == hypothesis.hypothesis_id
    root = parts["tree"].root
    assert [winner.candidate_id for winner in root.winners] == [
        hypothesis.hypothesis_id
    ]
    assert root.strategy["action"] == "promote"
    assert parts["sessions"].session.status == AgentSessionStatus.ACTIVE
    streams = {event.session_id for event in parts["events"].items}
    assert f"s1#exp#{experiment.experiment_id}" in streams


def test_winners_on_distinct_components_are_combined_once_and_in_series() -> None:
    use_case, parts = _system(["model", "configuration"])
    use_case.execute("s1")
    for number in list(parts["iterations"].items):
        use_case.run_candidate("s1", number)
    assert parts["tree"].root.strategy["action"] == "combine"

    assert use_case.execute("s1") == "dispatched_1"

    combination = next(
        item
        for item in parts["hypotheses"].items.values()
        if item.scope["area"] == "combination"
    )
    assert len(combination.depends_on) == 2
    number = parts["dispatcher"].dispatched[-1][1]
    assert use_case.run_candidate("s1", number) == "iteration_completed"
    combined = next(
        item
        for item in parts["experiments"].items.values()
        if item.candidate_id == combination.hypothesis_id
    )
    assert combined.kind is AgentExperimentKind.COMBINATION
    changed = {
        pin.component
        for pin in combined.components
        if pin not in combined.baseline_components
    }
    assert changed == {"model", "configuration"}
    root = parts["tree"].root
    assert root.winners[0].candidate_id == combination.hypothesis_id
    assert {pin.component for pin in root.winning_components if pin not in BASE} == {
        "model",
        "configuration",
    }


def test_run_with_winners_and_nothing_left_completes_with_its_strategy() -> None:
    use_case, parts = _system(["model"])
    use_case.execute("s1")
    use_case.run_candidate("s1", 1)

    assert use_case.execute("s1") == "completed_with_winners"

    assert parts["sessions"].session.status == AgentSessionStatus.COMPLETED
    assert parts["tree"].root.status is OptimizationRunStatus.COMPLETED
    assert parts["tree"].root.strategy["action"] == "promote"


def test_run_without_winners_asks_the_channel_manager_for_context() -> None:
    use_case, parts = _system(["library"], {"library": 0.5})
    use_case.execute("s1")
    use_case.run_candidate("s1", 1)

    assert use_case.execute("s1") == "blocked_no_context"
    assert parts["sessions"].session.block["code"] == "CONTEXT_MISSING"


def test_root_updates_retry_when_a_sibling_candidate_finished_first() -> None:
    use_case, parts = _system(["model"])
    use_case.execute("s1")
    parts["tree"].conflicts_to_raise = 2

    use_case.run_candidate("s1", 1)

    assert parts["tree"].root.winners


def test_a_finished_or_unknown_candidate_job_is_ignored() -> None:
    use_case, parts = _system(["model"])
    use_case.execute("s1")
    use_case.run_candidate("s1", 1)

    assert use_case.run_candidate("s1", 1) == "candidate_not_running"
    assert use_case.run_candidate("s1", 99) == "candidate_not_running"
