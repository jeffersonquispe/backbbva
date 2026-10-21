from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from src.application.ports.agent_experiment_evaluator_port import (
    AgentExperimentEvaluator,
)
from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_snapshot_port import DatasetSnapshotRepository
from src.application.use_cases.agent.evaluate_agent_experiment import (
    AgentExperimentPolicyError,
    EvaluateAgentExperiment,
)
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.domain.agents.objective import AgentObjective, AgentObjectiveStatus
from src.domain.datasets.mature_sample_entities import DatasetSnapshot
from src.domain.datasets.mature_sampling import content_hash

NOW = datetime(2026, 10, 20, tzinfo=UTC)
SHA = "a" * 64


class InMemoryAgentExperiments(AgentExperimentRepository):
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], AgentExperiment] = {}

    def create(self, experiment):
        key = (experiment.session_id, experiment.experiment_id)
        if key in self.items:
            raise ValueError("experiment already exists")
        self.items[key] = experiment
        return experiment

    def get(self, session_id, experiment_id):
        return self.items.get((session_id, experiment_id))

    def list_for_session(self, session_id, limit=50):
        return [item for item in self.items.values() if item.session_id == session_id][
            :limit
        ]

    def update(self, experiment, *, expected_status):
        key = (experiment.session_id, experiment.experiment_id)
        current = self.items[key]
        if current.status.value != expected_status:
            raise ValueError("stale status")
        if current.components != experiment.components:
            raise ValueError("immutable component refs changed")
        if current.snapshot_id != experiment.snapshot_id:
            raise ValueError("immutable sample reference changed")
        self.items[key] = experiment
        return experiment


class InMemoryAgentObjectives(AgentObjectiveRepository):
    def __init__(self) -> None:
        self.objective = AgentObjective(
            objective_id="fraud",
            version=4,
            success_label="label",
            positive_label="fraud",
            negative_label="not_fraud",
            maturing_days=30,
            expected_coverage_pct=95,
            stable_months=3,
            primary_metrics=("recall",),
            precision_floor=0.9,
            minimum_support_per_segment=30,
            minimum_global_support=100,
            minimum_count_to_publish_aggregates=30,
            minimum_mature_alert_coverage_pct=80,
            unlabeled_rule="exclude",
            schema_mapping={},
            status=AgentObjectiveStatus.ACTIVE,
            created_by="manager",
            created_at=NOW,
        )

    def get(self, objective_id, version):
        if (objective_id, version) == (
            self.objective.objective_id,
            self.objective.version,
        ):
            return self.objective
        return None

    def create(self, objective):
        return objective

    def list_versions(self, objective_id):
        return [self.objective]

    def get_active(self, objective_id):
        return self.objective

    def activate(self, objective, *, expected_active_version):
        return objective


class FixedClock:
    def now(self):
        return NOW


class InMemorySnapshots(DatasetSnapshotRepository):
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get(self, snapshot_id):
        return self.snapshot if self.snapshot.snapshot_id == snapshot_id else None

    def create(self, snapshot):
        self.snapshot = snapshot
        return snapshot

    def list_recent(self, limit):
        return [self.snapshot][:limit]

    def delete(self, snapshot_id):
        if self.snapshot.snapshot_id == snapshot_id:
            self.snapshot = None


class InMemoryDatasets(DatasetRepository):
    def __init__(self, datasets):
        self.datasets = datasets

    def get_rows(self, name):
        return self.datasets[name]


def _sample():
    partitions = {
        name: [{"fraud_label": "fraud"}]
        for name in ("training", "validation", "test", "final")
    }
    all_rows = [
        {**row, "__aria_partition": name}
        for name, rows in partitions.items()
        if name != "final"
        for row in rows
    ]
    refs = {name: f"snapshot-{name}" for name in (*partitions, "all")}
    datasets = {refs[name]: rows for name, rows in partitions.items()}
    datasets[refs["all"]] = all_rows
    snapshot = DatasetSnapshot(
        snapshot_id="snapshot-final-1",
        specification={
            "as_of": "2026-10-20",
            "maturing_days": 4,
            "content_hash_format": "persisted_csv_rows_v1",
        },
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        maturing_days=4,
        strata_counts={},
        partition_counts={name: len(rows) for name, rows in partitions.items()},
        schema_versions=(1,),
        content_hash=content_hash({**partitions, "all": all_rows}),
        trigger="test",
        dataset_refs=refs,
        created_at=NOW,
    )
    return snapshot, datasets


class RecordingEvaluator(AgentExperimentEvaluator):
    def __init__(
        self,
        result=None,
        error=None,
        mismatch_baseline_sample=False,
        mismatch_sample_hash=False,
    ) -> None:
        self.result = result
        self.error = error
        self.mismatch_baseline_sample = mismatch_baseline_sample
        self.mismatch_sample_hash = mismatch_sample_hash
        self.references = None
        self.sample_rows = None

    def evaluate(
        self,
        *,
        components,
        baseline_components,
        snapshot,
        final_rows,
        objective_id,
        objective_version,
    ):
        self.references = (components, baseline_components)
        self.sample_rows = final_rows
        if self.error:
            raise self.error
        result = self.result or _evidence_for(components, baseline_components)
        sample_ref = {
            "snapshot_id": snapshot.snapshot_id,
            "content_sha256": (
                "f" * 64 if self.mismatch_sample_hash else snapshot.content_hash
            ),
            "partition": "final",
        }
        result["sample"] = sample_ref
        result["baseline_sample"] = (
            {**sample_ref, "snapshot_id": "other-snapshot"}
            if self.mismatch_baseline_sample
            else sample_ref
        )
        result["candidate_sample"] = sample_ref
        return result


def _passing_evidence():
    candidate = {
        "component": "configuration",
        "entity_id": "config-2",
        "version": "3",
        "content_sha256": SHA,
    }
    baseline = {
        "component": "configuration",
        "entity_id": "baseline-config-2",
        "version": "baseline-v1",
        "content_sha256": "b" * 64,
    }
    return {
        "sample": {
            "snapshot_id": "snapshot-final-1",
            "content_sha256": "c" * 64,
            "partition": "final",
        },
        "evaluated_components": [candidate],
        "evaluated_baseline_components": [baseline],
        "uncertainty": {
            "method": "paired_bootstrap",
            "confidence_level": 0.95,
            "resamples": 1000,
        },
        "knowledge_evidence": {
            "decision_policy": "evidence_only_v1",
            "candidate_asset_count": 1,
            "baseline_asset_count": 1,
        },
        "delta": {
            "recall": {
                "estimate": 0.03,
                "ci95_lower": 0.01,
                "ci95_upper": 0.05,
            }
        },
        "baseline_global": {"precision": 0.92, "recall": 0.80},
        "global": {
            "eligible_count": 120,
            "positive_support": 40,
            "precision": 0.94,
            "recall": 0.83,
            "mature_label_coverage_pct": 91.5,
        },
        "segments": {
            "channel_digital": {
                "support": 45,
                "precision": 0.92,
                "recall": 0.81,
                "baseline_precision": 0.89,
                "baseline_recall": 0.78,
                "delta_precision": {
                    "estimate": 0.03,
                    "ci95_lower": 0.01,
                    "ci95_upper": 0.05,
                },
                "delta_recall": {
                    "estimate": 0.03,
                    "ci95_lower": 0.01,
                    "ci95_upper": 0.05,
                },
            },
            "channel_phone": {
                "support": 38,
                "precision": 0.91,
                "recall": 0.79,
                "baseline_precision": 0.90,
                "baseline_recall": 0.79,
                "delta_precision": {
                    "estimate": 0.01,
                    "ci95_lower": -0.01,
                    "ci95_upper": 0.03,
                },
                "delta_recall": {
                    "estimate": 0.0,
                    "ci95_lower": -0.02,
                    "ci95_upper": 0.02,
                },
            },
        },
    }


def _reference(component="configuration", entity_id="config-2", version="3"):
    return ComponentVersionReference(
        component=component,
        entity_id=entity_id,
        version=version,
        content_sha256=SHA,
    )


def _baseline(components):
    return tuple(
        ComponentVersionReference(
            component=item.component,
            entity_id=f"baseline-{item.entity_id}",
            version="baseline-v1",
            content_sha256="b" * 64,
        )
        for item in components
    )


def _evidence_for(components, baseline_components):
    result = _passing_evidence()
    result["evaluated_components"] = [
        {
            "component": item.component,
            "entity_id": item.entity_id,
            "version": item.version,
            "content_sha256": item.content_sha256,
        }
        for item in components
    ]
    result["evaluated_baseline_components"] = [
        {
            "component": item.component,
            "entity_id": item.entity_id,
            "version": item.version,
            "content_sha256": item.content_sha256,
        }
        for item in baseline_components
    ]
    return result


def _use_case(experiments=None, evaluator=None, snapshots=None, datasets=None):
    sample_snapshot, sample_datasets = _sample()
    return EvaluateAgentExperiment(
        experiments=experiments or InMemoryAgentExperiments(),
        objectives=InMemoryAgentObjectives(),
        evaluator=evaluator or RecordingEvaluator(),
        snapshots=snapshots or InMemorySnapshots(sample_snapshot),
        datasets=InMemoryDatasets(
            datasets if datasets is not None else sample_datasets
        ),
        clock=FixedClock(),
    )


def test_isolated_evaluation_persists_exact_pins_and_safe_aggregates():
    experiments = InMemoryAgentExperiments()
    evaluator = RecordingEvaluator()
    use_case = _use_case(experiments, evaluator)
    reference = _reference()

    result = use_case.execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(reference,),
        baseline_components=_baseline((reference,)),
        objective_id="fraud",
        objective_version=4,
    )

    assert result.status == AgentExperimentStatus.SUCCEEDED
    assert result.components == (reference,)
    assert result.global_evaluation["global"]["eligible_count"] == 120
    assert result.global_evaluation["sample"]["snapshot_id"] == "snapshot-final-1"
    assert result.global_evaluation["delta"]["recall"]["ci95_lower"] == 0.01
    assert result.global_evaluation["segments"]["channel_digital"]["support"] == 45
    assert (
        result.global_evaluation["segments"]["channel_digital"]["delta"]["precision"][
            "ci95_lower"
        ]
        == 0.01
    )
    assert evaluator.references == ((reference,), _baseline((reference,)))
    assert evaluator.sample_rows == [{"fraud_label": "fraud"}]
    assert (
        result.snapshot_sha256 == result.global_evaluation["sample"]["content_sha256"]
    )
    assert experiments.get("session-1", "exp-1") == result


def test_segment_aggregates_under_thirty_are_suppressed_without_rejection():
    result = _passing_evidence()
    result["segments"]["channel_phone"]["support"] = 29
    experiments = InMemoryAgentExperiments()
    evaluator = RecordingEvaluator(result)

    evaluated = _use_case(experiments, evaluator).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.SUCCEEDED
    assert "channel_phone" not in evaluated.global_evaluation["segments"]
    assert "channel_phone" not in str(evaluated.global_evaluation["constraints"])
    assert evaluated.global_evaluation["minimum_protected_segment_size"] == 30
    assert all(
        item["constraint_id"] != "minimum_segment_support"
        for item in evaluated.global_evaluation["constraints"]
    )


def test_combination_requires_previously_successful_isolated_evidence():
    experiments = InMemoryAgentExperiments()
    use_case = _use_case(experiments)

    failed = use_case.execute(
        experiment_id="combo-1",
        session_id="session-1",
        kind=AgentExperimentKind.COMBINATION,
        iteration_number=3,
        components=(_reference(), _reference("model", "model-1", "b" * 64)),
        baseline_components=_baseline(
            (_reference(), _reference("model", "model-1", "b" * 64))
        ),
        objective_id="fraud",
        objective_version=4,
    )
    assert failed.status == AgentExperimentStatus.FAILED
    assert failed.error_code == "ISOLATED_EVIDENCE_REQUIRED"


def test_combination_is_evaluated_only_after_isolated_evidence():
    experiments = InMemoryAgentExperiments()
    configuration = _reference()
    model = _reference("model", "model-1", "artifact-v1")
    baseline_components = _baseline((configuration, model))
    evaluator = RecordingEvaluator()
    use_case = _use_case(experiments, evaluator)
    isolated_candidates = (
        (configuration, baseline_components[1]),
        (baseline_components[0], model),
    )
    for index, candidate_components in enumerate(isolated_candidates, start=1):
        isolated = use_case.execute(
            experiment_id=f"isolated-{index}",
            session_id="session-1",
            kind=AgentExperimentKind.ISOLATED,
            iteration_number=index,
            components=candidate_components,
            baseline_components=baseline_components,
            objective_id="fraud",
            objective_version=4,
        )
        assert isolated.status == AgentExperimentStatus.SUCCEEDED

    combined = use_case.execute(
        experiment_id="combo-1",
        session_id="session-1",
        kind=AgentExperimentKind.COMBINATION,
        iteration_number=3,
        components=(configuration, model),
        baseline_components=baseline_components,
        objective_id="fraud",
        objective_version=4,
    )

    assert combined.status == AgentExperimentStatus.SUCCEEDED
    assert combined.components == (configuration, model)


def test_four_component_combination_uses_one_verified_final_sample():
    experiments = InMemoryAgentExperiments()
    baseline_components = tuple(
        _reference(component, f"baseline-{component}", "1")
        for component in ("model", "configuration", "library", "vector_store")
    )
    candidate_components = tuple(
        _reference(component, f"candidate-{component}", "2")
        for component in ("model", "configuration", "library", "vector_store")
    )
    evaluator = RecordingEvaluator()
    use_case = _use_case(experiments, evaluator)

    for index, changed_component in enumerate(range(4), start=1):
        isolated_candidate = tuple(
            candidate_components[position]
            if position == changed_component
            else baseline_components[position]
            for position in range(4)
        )
        result = use_case.execute(
            experiment_id=f"isolated-{index}",
            session_id="session-four",
            kind=AgentExperimentKind.ISOLATED,
            iteration_number=index,
            components=isolated_candidate,
            baseline_components=baseline_components,
            objective_id="fraud",
            objective_version=4,
        )
        assert result.status == AgentExperimentStatus.SUCCEEDED

    combined = use_case.execute(
        experiment_id="combination-all-components",
        session_id="session-four",
        kind=AgentExperimentKind.COMBINATION,
        iteration_number=5,
        components=candidate_components,
        baseline_components=baseline_components,
        objective_id="fraud",
        objective_version=4,
    )

    assert combined.status == AgentExperimentStatus.SUCCEEDED
    assert evaluator.references == (candidate_components, baseline_components)
    assert combined.snapshot_id == "snapshot-final-1"
    assert evaluator.sample_rows == [{"fraud_label": "fraud"}]
    assert combined.global_evaluation["uncertainty"] == {
        "method": "paired_bootstrap",
        "confidence_level": 0.95,
        "resamples": 1000,
    }


def test_aggregate_without_exact_pins_and_paired_uncertainty_cannot_succeed():
    evidence = _passing_evidence()
    del evidence["delta"]

    evaluated = _use_case(evaluator=RecordingEvaluator(evidence)).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.FAILED
    assert evaluated.error_code == "GLOBAL_EVIDENCE_INVALID"
    assert evaluated.global_evaluation == {}


def test_runner_cannot_report_success_for_different_component_pin():
    evidence = _passing_evidence()
    evidence["evaluated_components"][0]["content_sha256"] = "d" * 64

    evaluated = _use_case(evaluator=RecordingEvaluator(evidence)).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.FAILED
    assert evaluated.error_code == "GLOBAL_EVIDENCE_INVALID"
    assert evaluated.global_evaluation == {}


def test_runner_cannot_report_success_when_baseline_used_a_different_sample():
    evaluated = _use_case(
        evaluator=RecordingEvaluator(mismatch_baseline_sample=True)
    ).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.FAILED
    assert evaluated.error_code == "GLOBAL_EVIDENCE_INVALID"


def test_runner_cannot_report_success_when_evaluation_hash_differs_from_snapshot():
    evaluated = _use_case(
        evaluator=RecordingEvaluator(mismatch_sample_hash=True)
    ).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.FAILED
    assert evaluated.error_code == "GLOBAL_EVIDENCE_INVALID"


def test_modified_snapshot_rows_fail_hash_verification_before_scoring():
    snapshot, dataset_rows = _sample()
    dataset_rows[snapshot.dataset_refs["final"]][0]["fraud_label"] = "no_fraud"
    evaluator = RecordingEvaluator()

    failed = _use_case(
        evaluator=evaluator,
        snapshots=InMemorySnapshots(snapshot),
        datasets=dataset_rows,
    ).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert failed.status == AgentExperimentStatus.FAILED
    assert failed.error_code == "FINAL_MATURE_SNAPSHOT_UNAVAILABLE"
    assert evaluator.sample_rows is None


def test_global_constraint_failure_is_rejected_without_persisting_raw_error():
    result = _passing_evidence()
    result["global"]["precision"] = 0.75
    experiments = InMemoryAgentExperiments()

    evaluated = _use_case(experiments, RecordingEvaluator(result)).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.REJECTED_GLOBAL_CONSTRAINT
    assert any(
        item["constraint_id"] == "global_precision_floor" and item["status"] == "FAILED"
        for item in evaluated.global_evaluation["constraints"]
    )
    assert evaluated.error_code is None


def test_combination_is_rejected_when_primary_global_metric_regresses():
    result = _passing_evidence()
    result["global"]["recall"] = 0.79
    result["delta"]["recall"] = {
        "estimate": -0.01,
        "ci95_lower": -0.03,
        "ci95_upper": 0.01,
    }

    evaluated = _use_case(evaluator=RecordingEvaluator(result)).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.REJECTED_GLOBAL_CONSTRAINT
    assert any(
        item["constraint_id"] == "global_primary_metric_non_regression:recall"
        and item["aggregate"] == -0.01
        for item in evaluated.global_evaluation["constraints"]
    )


def test_evaluator_error_is_safely_failed():
    evaluated = _use_case(
        evaluator=RecordingEvaluator(error=RuntimeError("sensitive payload"))
    ).execute(
        experiment_id="exp-1",
        session_id="session-1",
        kind=AgentExperimentKind.ISOLATED,
        iteration_number=1,
        components=(_reference(),),
        baseline_components=_baseline((_reference(),)),
        objective_id="fraud",
        objective_version=4,
    )

    assert evaluated.status == AgentExperimentStatus.FAILED
    assert evaluated.error_code == "GLOBAL_EVALUATION_FAILED"
    assert evaluated.global_evaluation == {}


def test_reference_hash_must_be_exact_sha256():
    ref = replace(_reference(), content_sha256="not-a-hash")
    with pytest.raises(AgentExperimentPolicyError, match="COMPONENT_REFERENCE_INVALID"):
        _use_case().execute(
            experiment_id="exp-1",
            session_id="session-1",
            kind=AgentExperimentKind.ISOLATED,
            iteration_number=1,
            components=(ref,),
            baseline_components=_baseline((ref,)),
            objective_id="fraud",
            objective_version=4,
        )


def test_component_reference_pin_is_stable_for_canonical_content():
    first = ComponentVersionReference.pin(
        "CONFIGURATION", "config-1", "v3", {"threshold": 0.7, "enabled": True}
    )
    second = ComponentVersionReference.pin(
        "configuration", "config-1", "v3", {"enabled": True, "threshold": 0.7}
    )

    assert first == second
    assert first.component == "configuration"
    assert len(first.content_sha256) == 64
