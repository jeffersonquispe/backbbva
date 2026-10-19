from datetime import UTC, date, datetime
from uuid import uuid4

from src.application.ports.agent_verification_port import AgentVerification
from src.application.ports.model_port import ModelRecord, ModelStatus
from src.application.use_cases.agent.evaluate_global_pipeline import (
    GLOBAL_PIPELINE_VERIFICATION_ID,
    EvaluateGlobalPipeline,
)
from src.domain.agents.objective import AgentObjective, AgentObjectiveStatus
from src.domain.datasets.mature_sample_entities import DatasetSnapshot


class InMemorySnapshots:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get(self, snapshot_id):
        return self.snapshot if self.snapshot.snapshot_id == snapshot_id else None


class InMemoryDatasets:
    def __init__(self, rows):
        self.rows = rows

    def get_rows(self, name):
        assert name == "snapshot-final"
        return self.rows


class InMemoryModels:
    def __init__(self, models):
        self.models = {model.id: model for model in models}

    def get(self, model_id):
        return self.models.get(model_id)


class InMemoryObjectives:
    def __init__(self, objective):
        self.objective = objective

    def get(self, objective_id, version):
        return self.objective if (objective_id, version) == (self.objective.objective_id, self.objective.version) else None


class InMemoryVerifications:
    def __init__(self, reservation):
        self.reservation = reservation

    def get(self, subject_id, verification_id):
        if (subject_id, verification_id) == (
            self.reservation.subject_id,
            self.reservation.verification_id,
        ):
            return self.reservation
        return None

    def update(self, verification, *, expected_status):
        assert self.reservation.status == expected_status
        self.reservation = verification
        return verification


class FixedEvaluator:
    def __init__(self, candidate, baseline):
        self.candidate = candidate
        self.baseline = baseline

    def predict_positive(self, model, rows):
        return self.candidate if model.tag == "candidate" else self.baseline


class FixedClock:
    def now(self):
        return datetime(2026, 10, 19, tzinfo=UTC)


def test_global_evaluation_compares_both_models_only_on_mature_final_labels():
    rows = [
        {"fraud_label": "fraud" if index < 20 else "no_fraud"}
        for index in range(40)
    ]
    rows.append({"fraud_label": "pending"})
    snapshot = DatasetSnapshot(
        snapshot_id="snapshot-1",
        specification={},
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        maturing_days=4,
        strata_counts={},
        partition_counts={"final": len(rows)},
        schema_versions=(1,),
        content_hash="f" * 64,
        trigger="manual",
        dataset_refs={"final": "snapshot-final"},
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    candidate = ModelRecord(
        id=uuid4(), tag="candidate", description="", status=ModelStatus.READY,
        dataset_name="", target_field="fraud_label",
    )
    baseline = ModelRecord(
        id=uuid4(), tag="baseline", description="", status=ModelStatus.READY,
        dataset_name="", target_field="fraud_label", active=True,
    )
    objective = AgentObjective(
        objective_id="global_fraud_effectiveness", version=2,
        success_label="fraud_label", positive_label="fraud", negative_label="no_fraud",
        maturing_days=4, expected_coverage_pct=98, stable_months=6,
        primary_metrics=("precision", "recall"), precision_floor=0.8,
        minimum_support_per_segment=30, minimum_global_support=30,
        minimum_count_to_publish_aggregates=30,
        minimum_mature_alert_coverage_pct=80,
        unlabeled_rule="exclude_pending_from_precision_and_recall",
        schema_mapping={}, status=AgentObjectiveStatus.ACTIVE,
        created_by="manager", created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    reservation = AgentVerification(
        verification_id=GLOBAL_PIPELINE_VERIFICATION_ID,
        subject_id=snapshot.snapshot_id,
        verifier="global_pipeline_evaluation",
        status="PENDING",
        safe_metrics={
            "candidate_model_id": str(candidate.id),
            "baseline_model_id": str(baseline.id),
            "objective_id": objective.objective_id,
            "objective_version": objective.version,
            "snapshot_hash": snapshot.content_hash,
            "partition": "final",
        },
    )
    verifications = InMemoryVerifications(reservation)
    evaluator = FixedEvaluator(
        candidate=[True] * 20 + [False] * 21,
        baseline=[True] * 10 + [False] * 10 + [True] * 10 + [False] * 10 + [False],
    )

    result = EvaluateGlobalPipeline(
        snapshots=InMemorySnapshots(snapshot),
        datasets=InMemoryDatasets(rows),
        models=InMemoryModels([candidate, baseline]),
        objectives=InMemoryObjectives(objective),
        verifications=verifications,
        evaluator=evaluator,
        clock=FixedClock(),
    ).execute(snapshot_id=snapshot.snapshot_id)

    assert result.status == "SUCCEEDED"
    assert result.safe_metrics["partition"] == "final"
    assert result.safe_metrics["eligible_count"] == 40
    assert result.safe_metrics["candidate"]["recall"] == 1.0
    assert result.safe_metrics["baseline"]["recall"] == 0.5
    assert result.safe_metrics["candidate_minus_baseline_recall_ci95"][0] > 0
    assert "customer_id" not in str(result.safe_metrics)
