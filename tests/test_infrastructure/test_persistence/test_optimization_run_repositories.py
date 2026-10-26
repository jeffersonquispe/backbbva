from datetime import UTC, datetime

from src.application.ports.agent_hypothesis_port import (
    AgentHypothesis,
    AgentHypothesisStatus,
)
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.domain.agents.optimization_run import (
    OptimizationRun,
    OptimizationRunStatus,
    RunWinner,
    experiment_stream_key,
)
from src.infrastructure.persistence.database.dynamodb.repositories.optimization_run_repositories import (
    experiment_from_item,
    experiment_to_item,
    hypothesis_from_item,
    hypothesis_to_item,
    run_from_item,
    run_to_item,
)

NOW = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
PIN = ComponentVersionReference("model", "model-1", "1", "a" * 64)


def test_root_node_keeps_base_configuration_winners_and_strategy() -> None:
    run = OptimizationRun(
        run_id="s1",
        status=OptimizationRunStatus.RUNNING,
        created_at=NOW,
        updated_at=NOW,
        objective_id="o1",
        objective_version=2,
        baseline_components=(PIN,),
        budget_limits={"tokens": 100},
        optimizer_settings={"max_parallel_experiments": 3},
        scope_areas=("model", "configuration"),
        insight_ids=("i1",),
        memory_insight_ids=("m1",),
        winners=(RunWinner("h1", "e1", "configuration", 0.7, 0.9, 0.1),),
        winning_components=(PIN,),
        strategy={"action": "combine", "rationale": "dos ganadores"},
        events_stream="s1",
        rev=3,
    )

    item = run_to_item(run)

    assert item["node"] == "RUN"
    assert run_from_item({**item, "run_id": "s1"}) == run


def test_candidate_node_carries_its_own_insights_dependencies_and_conclusion() -> None:
    hypothesis = AgentHypothesis(
        session_id="s1",
        hypothesis_id="h1",
        statement="Combinar configuración y modelo",
        scope={"area": "combination"},
        priority=50,
        status=AgentHypothesisStatus.VALIDATED,
        created_at=NOW,
        updated_at=NOW,
        depends_on=("h2", "h3"),
        insight_ids=("i9",),
        conclusion={"verdict": "VALIDATED", "recall_delta": 0.12},
        rev=2,
    )

    item = hypothesis_to_item(hypothesis)

    assert (item["run_id"], item["node"]) == ("s1", "CAND#h1")
    assert hypothesis_from_item(item) == hypothesis


def test_experiment_node_points_to_its_own_event_stream_and_candidate() -> None:
    experiment = AgentExperiment(
        session_id="s1",
        experiment_id="e1",
        iteration_number=2,
        kind=AgentExperimentKind.ISOLATED,
        status=AgentExperimentStatus.SUCCEEDED,
        components=(PIN,),
        objective_id="o1",
        objective_version=1,
        created_at=NOW,
        baseline_components=(PIN,),
        global_evaluation={"eligible_count": 40},
        candidate_id="h1",
    )

    item = experiment_to_item(experiment)

    assert item["node"] == "EXP#e1"
    assert item["events_stream"] == experiment_stream_key("s1", "e1") == "s1#exp#e1"
    assert experiment_from_item(item) == experiment
