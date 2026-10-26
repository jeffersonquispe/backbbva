from datetime import UTC, datetime

from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.domain.agents.optimization_run import component_for_area, rank_winners

NOW = datetime(2026, 10, 26, tzinfo=UTC)
BASE = {
    name: ComponentVersionReference(name, f"{name}-1", "1", "a" * 64)
    for name in ("model", "configuration")
}


def _experiment(experiment_id, changed, status, recall, base_recall=0.6, precision=0.92):
    components = dict(BASE)
    components[changed] = ComponentVersionReference(changed, f"{changed}-2", "2", "b" * 64)
    return AgentExperiment(
        session_id="s1",
        experiment_id=experiment_id,
        iteration_number=1,
        kind=AgentExperimentKind.ISOLATED,
        status=status,
        components=tuple(components.values()),
        baseline_components=tuple(BASE.values()),
        objective_id="o1",
        objective_version=1,
        created_at=NOW,
        global_evaluation={
            "candidate": {"recall": recall, "precision": precision},
            "baseline": {"recall": base_recall, "precision": 0.9},
        },
    )


def test_winners_are_succeeded_improvements_ranked_by_recall() -> None:
    winners = rank_winners(
        [
            ("h1", _experiment("e1", "model", AgentExperimentStatus.SUCCEEDED, 0.7)),
            ("h2", _experiment("e2", "configuration", AgentExperimentStatus.SUCCEEDED, 0.8)),
            ("h3", _experiment("e3", "model", AgentExperimentStatus.FAILED, 0.95)),
            ("h4", _experiment("e4", "model", AgentExperimentStatus.SUCCEEDED, 0.55)),
        ]
    )

    assert [item.candidate_id for item in winners] == ["h2", "h1"]
    assert winners[0].component == "configuration"
    assert round(winners[0].recall_delta, 2) == 0.2


def test_areas_map_to_the_component_they_change() -> None:
    assert component_for_area("xgboost") == component_for_area("model") == "model"
    assert component_for_area("library") == "library"
    assert component_for_area("combination") is None
