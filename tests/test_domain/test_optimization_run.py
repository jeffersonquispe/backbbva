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


def test_metrics_are_read_from_the_published_evaluation_shape():
    from src.domain.agents.optimization_run import experiment_metrics

    published = {
        "sample": {"eligible_count": 88, "partition": "final"},
        "metrics": {
            "candidate": {"precision": 0.95, "recall": 0.72, "eligible_count": 88},
            "baseline": {"precision": 0.93, "recall": 0.6},
        },
    }
    legacy = {
        "eligible_count": 40,
        "candidate": {"recall": 0.7},
        "baseline": {"recall": 0.6},
    }

    assert experiment_metrics(published).candidate["recall"] == 0.72
    assert experiment_metrics(published).baseline["recall"] == 0.6
    assert experiment_metrics(published).eligible_count == 88
    assert experiment_metrics(legacy).eligible_count == 40
    assert experiment_metrics(None).candidate == {}


def test_winners_are_ranked_from_the_published_shape_too():
    experiment = _experiment("e1", "model", AgentExperimentStatus.SUCCEEDED, 0.7)
    published = experiment.__class__(
        **{
            **experiment.__dict__,
            "global_evaluation": {
                "sample": {"eligible_count": 120},
                "metrics": {
                    "candidate": {"recall": 0.74, "precision": 0.95},
                    "baseline": {"recall": 0.6, "precision": 0.93},
                },
            },
        }
    )

    winners = rank_winners([("h1", published)])

    assert [item.candidate_id for item in winners] == ["h1"]
    assert round(winners[0].recall_delta, 2) == 0.14
