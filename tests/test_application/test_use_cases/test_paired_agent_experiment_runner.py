from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
    ResolvedAgentComponent,
)
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_pipeline_scorer_port import AgentPipelineScorer
from src.application.use_cases.agent.paired_agent_experiment_runner import (
    PairedAgentExperimentRunner,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.objective import AgentObjective, AgentObjectiveStatus
from src.domain.datasets.mature_sample_entities import DatasetSnapshot


class InMemoryComponentResolver(AgentExperimentComponentResolver):
    def __init__(self, contents):
        self.contents = contents

    def resolve(self, reference):
        content = self.contents.get(reference)
        return (
            ResolvedAgentComponent(reference=reference, content=content)
            if content is not None
            else None
        )


class RecordingPipelineScorer(AgentPipelineScorer):
    def __init__(self):
        self.calls = []

    def predict_positive(self, components, rows, *, snapshot):
        self.calls.append((components, rows, snapshot))
        return [all(component.content["positive"] for component in components)] * len(rows)


class InMemoryObjectives(AgentObjectiveRepository):
    def __init__(self, protected_segments=None):
        self.objective = AgentObjective(
            objective_id="fraud",
            version=3,
            success_label="fraud_label",
            positive_label="fraud",
            negative_label="no_fraud",
            maturing_days=30,
            expected_coverage_pct=95,
            stable_months=3,
            primary_metrics=("precision", "recall"),
            precision_floor=0.25,
            minimum_support_per_segment=30,
            minimum_global_support=30,
            minimum_count_to_publish_aggregates=30,
            minimum_mature_alert_coverage_pct=80,
            unlabeled_rule="exclude_pending_from_precision_and_recall",
            schema_mapping={"protected_segments": protected_segments or {}},
            status=AgentObjectiveStatus.ACTIVE,
            created_by="test",
            created_at=datetime(2026, 10, 20, tzinfo=UTC),
        )

    def get(self, objective_id, version):
        return (
            self.objective
            if (objective_id, version)
            == (self.objective.objective_id, self.objective.version)
            else None
        )

    def create(self, objective):
        return objective

    def list_versions(self, objective_id):
        return [self.objective]

    def get_active(self, objective_id):
        return self.objective

    def activate(self, objective, *, expected_active_version):
        return objective


def _objective_repo(protected_segments=None):
    return InMemoryObjectives(protected_segments)


def _reference(component, version, positive):
    return ComponentVersionReference.pin(
        component,
        f"{component}-{version}",
        version,
        {"positive": positive},
    )


def _snapshot():
    return DatasetSnapshot(
        snapshot_id="mature-final-1",
        specification={"as_of": "2026-10-20", "maturing_days": 30},
        period_start=datetime(2026, 9, 1, tzinfo=UTC).date(),
        period_end=datetime(2026, 9, 30, tzinfo=UTC).date(),
        maturing_days=30,
        strata_counts={},
        partition_counts={"final": 40},
        schema_versions=(1,),
        content_hash="e" * 64,
        trigger="test",
        dataset_refs={"final": "final-sample"},
        created_at=datetime(2026, 10, 20, tzinfo=UTC),
    )


def _fixture(protected_segments=None):
    components = tuple(
        _reference(name, "candidate", True)
        for name in ("model", "configuration", "library", "vector_store")
    )
    baseline = tuple(
        _reference(name, "baseline", False)
        for name in ("model", "configuration", "library", "vector_store")
    )
    contents = {
        **{ref: {"positive": True} for ref in components},
        **{ref: {"positive": False} for ref in baseline},
    }
    resolver = InMemoryComponentResolver(contents)
    scorer = RecordingPipelineScorer()
    objectives = _objective_repo(protected_segments)
    runner = PairedAgentExperimentRunner(
        components=resolver,
        scorer=scorer,
        objectives=objectives,
    )
    rows = [
        {"fraud_label": "fraud" if index < 20 else "no_fraud"}
        for index in range(40)
    ]
    return runner, resolver, scorer, components, baseline, rows, objectives


def test_runner_applies_all_four_exact_pins_to_same_final_rows_and_bootstraps_pairwise():
    runner, _, scorer, components, baseline, rows, _ = _fixture()

    evidence = runner.evaluate(
        components=components,
        baseline_components=baseline,
        snapshot=_snapshot(),
        final_rows=rows,
        objective_id="fraud",
        objective_version=3,
    )

    assert [call[0] for call in scorer.calls] == [
        tuple(ResolvedAgentComponent(ref, {"positive": True}) for ref in components),
        tuple(ResolvedAgentComponent(ref, {"positive": False}) for ref in baseline),
    ]
    assert scorer.calls[0][1] is scorer.calls[1][1]
    assert scorer.calls[0][1] is rows
    assert evidence["sample"] == evidence["baseline_sample"] == evidence["candidate_sample"]
    assert evidence["evaluated_components"] == [
        {"component": ref.component, "entity_id": ref.entity_id,
         "version": ref.version, "content_sha256": ref.content_sha256}
        for ref in components
    ]
    assert evidence["global"]["recall"] == 1.0
    assert evidence["baseline_global"]["recall"] == 0.0
    # The baseline flagged nothing: precision is undefined, not 0.
    assert evidence["baseline_global"]["predicted_positive"] == 0
    assert evidence["baseline_global"]["precision"] is None
    assert evidence["baseline_global"]["f1"] is None
    assert evidence["delta"]["precision"]["estimate"] is None
    assert evidence["delta"]["recall"] == {
        "estimate": 1.0,
        "ci95_lower": 1.0,
        "ci95_upper": 1.0,
    }
    assert evidence["uncertainty"] == {
        "method": "paired_bootstrap",
        "confidence_level": 0.95,
        "resamples": 1000,
    }


def test_runner_suppresses_under_supported_allow_list_segments():
    runner, _, _, components, baseline, rows, _ = _fixture(
        {"channel": ["sparse", "protected"]}
    )
    rows[:29] = [
        {"fraud_label": "fraud" if index < 14 else "no_fraud", "channel": "sparse"}
        for index in range(29)
    ]
    rows[29:] = [
        {"fraud_label": "fraud" if index % 2 else "no_fraud", "channel": "protected"}
        for index in range(11)
    ]

    evidence = runner.evaluate(
        components=components,
        baseline_components=baseline,
        snapshot=_snapshot(),
        final_rows=rows,
        objective_id="fraud",
        objective_version=3,
    )

    assert "channel_sparse" not in evidence["segments"]
    assert "channel_protected" not in evidence["segments"]
    assert "sparse" not in str(evidence["segments"])


def test_runner_fails_closed_on_content_hash_corruption():
    runner, resolver, _, components, baseline, rows, _ = _fixture()
    resolver.contents[components[0]] = {"positive": False}

    with pytest.raises(ValueError, match="COMPONENT_PIN_HASH_MISMATCH"):
        runner.evaluate(
            components=components,
            baseline_components=baseline,
            snapshot=_snapshot(),
            final_rows=rows,
            objective_id="fraud",
            objective_version=3,
        )


def test_runner_fails_closed_when_any_exact_component_is_unresolvable():
    runner, resolver, _, components, baseline, rows, _ = _fixture()
    del resolver.contents[baseline[2]]

    with pytest.raises(ValueError, match="COMPONENT_PIN_UNRESOLVED"):
        runner.evaluate(
            components=components,
            baseline_components=baseline,
            snapshot=_snapshot(),
            final_rows=rows,
            objective_id="fraud",
            objective_version=3,
        )


def test_runner_rejects_non_final_snapshot():
    runner, _, _, components, baseline, rows, _ = _fixture()
    snapshot = _snapshot()
    snapshot = DatasetSnapshot(
        **{
            **snapshot.__dict__,
            "dataset_refs": {"test": "test-sample"},
        }
    )

    with pytest.raises(ValueError, match="FINAL_MATURE_SNAPSHOT_INVALID"):
        runner.evaluate(
            components=components,
            baseline_components=baseline,
            snapshot=snapshot,
            final_rows=rows,
            objective_id="fraud",
            objective_version=3,
        )
