from __future__ import annotations

import hashlib
import random
from dataclasses import replace

from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_verification_port import (
    AgentVerification,
    AgentVerificationRepository,
)
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_snapshot_port import DatasetSnapshotRepository
from src.application.ports.model_pipeline_evaluator_port import ModelPipelineEvaluator
from src.application.ports.model_port import ModelRepository, ModelStatus

GLOBAL_PIPELINE_VERIFICATION_ID = "global_pipeline"


class GlobalPipelineEvaluationError(Exception):
    pass


class StartGlobalPipelineEvaluation:
    def __init__(
        self,
        *,
        snapshots: DatasetSnapshotRepository,
        models: ModelRepository,
        objectives: AgentObjectiveRepository,
        verifications: AgentVerificationRepository,
        dispatcher,
        clock: Clock,
    ) -> None:
        self._snapshots = snapshots
        self._models = models
        self._objectives = objectives
        self._verifications = verifications
        self._dispatcher = dispatcher
        self._clock = clock

    def execute(self, *, snapshot_id: str, candidate_model_id: str) -> AgentVerification:
        snapshot = self._snapshots.get(snapshot_id)
        objective = self._objectives.get_active("global_fraud_effectiveness")
        if snapshot is None or "final" not in snapshot.dataset_refs:
            raise GlobalPipelineEvaluationError("Mature snapshot with final partition required")
        if objective is None:
            raise GlobalPipelineEvaluationError("An active objective is required")
        try:
            from uuid import UUID

            candidate = self._models.get(UUID(candidate_model_id))
        except ValueError as error:
            raise GlobalPipelineEvaluationError("Candidate model id is invalid") from error
        baseline = self._models.get_active()
        if candidate is None or candidate.status != ModelStatus.READY:
            raise GlobalPipelineEvaluationError("Candidate model must be READY")
        if baseline is None or baseline.status != ModelStatus.READY:
            raise GlobalPipelineEvaluationError("Active baseline model must be READY")
        if candidate.id == baseline.id:
            raise GlobalPipelineEvaluationError("Candidate and baseline must differ")
        if self._verifications.get(snapshot_id, GLOBAL_PIPELINE_VERIFICATION_ID):
            raise GlobalPipelineEvaluationError(
                "The final partition has already been reserved for evaluation"
            )
        verification = AgentVerification(
            verification_id=GLOBAL_PIPELINE_VERIFICATION_ID,
            subject_id=snapshot_id,
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
            created_at=self._clock.now(),
        )
        saved = self._verifications.create(verification)
        try:
            self._dispatcher.dispatch(snapshot_id)
        except Exception:  # noqa: BLE001 - fail closed without exposing row-derived errors
            self._verifications.update(
                replace(saved, status="FAILED", error_code="DISPATCH_FAILED"),
                expected_status="PENDING",
            )
            raise
        return saved


class EvaluateGlobalPipeline:
    def __init__(
        self,
        *,
        snapshots: DatasetSnapshotRepository,
        datasets: DatasetRepository,
        models: ModelRepository,
        objectives: AgentObjectiveRepository,
        verifications: AgentVerificationRepository,
        evaluator: ModelPipelineEvaluator,
        clock: Clock,
    ) -> None:
        self._snapshots = snapshots
        self._datasets = datasets
        self._models = models
        self._objectives = objectives
        self._verifications = verifications
        self._evaluator = evaluator
        self._clock = clock

    def execute(self, *, snapshot_id: str) -> AgentVerification:
        verification = self._verifications.get(
            snapshot_id, GLOBAL_PIPELINE_VERIFICATION_ID
        )
        if verification is None:
            raise GlobalPipelineEvaluationError("Evaluation reservation not found")
        if verification.status == "SUCCEEDED":
            return verification
        if verification.status != "PENDING":
            raise GlobalPipelineEvaluationError("Evaluation reservation is not pending")
        verification = replace(verification, status="RUNNING")
        self._verifications.update(verification, expected_status="PENDING")
        try:
            return self._evaluate(snapshot_id, verification)
        except Exception:  # noqa: BLE001 - fail closed without persisting row-derived errors
            self._verifications.update(
                replace(verification, status="FAILED", error_code="EVALUATION_FAILED"),
                expected_status="RUNNING",
            )
            raise GlobalPipelineEvaluationError(
                "Global pipeline evaluation failed"
            ) from None

    def _evaluate(self, snapshot_id: str, verification: AgentVerification):
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None or "final" not in snapshot.dataset_refs:
            raise GlobalPipelineEvaluationError("Final partition is unavailable")
        pinned = verification.safe_metrics
        if pinned.get("snapshot_hash") != snapshot.content_hash:
            raise GlobalPipelineEvaluationError("Snapshot content hash changed")
        objective = self._objectives.get(
            str(pinned["objective_id"]), int(pinned["objective_version"])
        )
        candidate = self._models.get(_uuid(str(pinned["candidate_model_id"])))
        baseline = self._models.get(_uuid(str(pinned["baseline_model_id"])))
        if objective is None or candidate is None or baseline is None:
            raise GlobalPipelineEvaluationError("Pinned evaluation inputs are unavailable")
        rows = self._datasets.get_rows(snapshot.dataset_refs["final"])
        labels = [row.get(objective.success_label) for row in rows]
        eligible = [
            index
            for index, label in enumerate(labels)
            if label in {objective.positive_label, objective.negative_label}
        ]
        support = sum(labels[index] == objective.positive_label for index in eligible)
        if len(eligible) < objective.minimum_global_support or support < 1:
            raise GlobalPipelineEvaluationError("Final partition does not meet objective support")
        candidate_predictions = self._evaluator.predict_positive(candidate, rows)
        baseline_predictions = self._evaluator.predict_positive(baseline, rows)
        if len(candidate_predictions) != len(rows) or len(baseline_predictions) != len(rows):
            raise GlobalPipelineEvaluationError("Scorer returned an invalid prediction count")
        truth = [labels[index] == objective.positive_label for index in eligible]
        candidate_pred = [candidate_predictions[index] for index in eligible]
        baseline_pred = [baseline_predictions[index] for index in eligible]
        candidate_metrics = _metrics(truth, candidate_pred)
        baseline_metrics = _metrics(truth, baseline_pred)
        recall_delta_ci = _paired_bootstrap_recall_delta(
            truth, candidate_pred, baseline_pred, snapshot.content_hash
        )
        precision_delta_ci = _paired_bootstrap_metric_delta(
            truth, candidate_pred, baseline_pred, snapshot.content_hash, "precision"
        )
        coverage = 100.0 * len(eligible) / max(1, len(rows))
        meets_objective = (
            candidate_metrics["precision"] >= objective.precision_floor
            and coverage >= objective.minimum_mature_alert_coverage_pct
            and support >= objective.minimum_global_support
        )
        outcome = (
            "CANDIDATE_BETTER"
            if meets_objective and recall_delta_ci[0] > 0
            else "NO_VERIFIED_IMPROVEMENT"
        )
        result = {
            **pinned,
            "status": outcome,
            "eligible_count": len(eligible),
            "positive_support": support,
            "mature_label_coverage_pct": round(coverage, 4),
            "candidate": candidate_metrics,
            "baseline": baseline_metrics,
            "candidate_minus_baseline_recall_ci95": [
                round(recall_delta_ci[0], 6), round(recall_delta_ci[1], 6)
            ],
            "candidate_minus_baseline_precision_ci95": [
                round(precision_delta_ci[0], 6), round(precision_delta_ci[1], 6)
            ],
        }
        completed = replace(
            verification,
            status="SUCCEEDED",
            safe_metrics=result,
            error_code=None,
        )
        return self._verifications.update(completed, expected_status="RUNNING")


def _uuid(value: str):
    from uuid import UUID

    return UUID(value)


def _metrics(truth: list[bool], predicted: list[bool]) -> dict[str, float | int]:
    tp = sum(actual and guess for actual, guess in zip(truth, predicted))
    fp = sum((not actual) and guess for actual, guess in zip(truth, predicted))
    fn = sum(actual and (not guess) for actual, guess in zip(truth, predicted))
    tn = sum((not actual) and (not guess) for actual, guess in zip(truth, predicted))
    return {
        "precision": round(tp / max(1, tp + fp), 6),
        "recall": round(tp / max(1, tp + fn), 6),
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
    }


def _paired_bootstrap_recall_delta(
    truth: list[bool], candidate: list[bool], baseline: list[bool], snapshot_hash: str
) -> tuple[float, float]:
    positive_indices = [index for index, value in enumerate(truth) if value]
    if not positive_indices:
        return (0.0, 0.0)
    seed = int(hashlib.sha256(snapshot_hash.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    deltas = []
    for _ in range(1000):
        sampled = [rng.choice(positive_indices) for _ in positive_indices]
        candidate_recall = sum(candidate[index] for index in sampled) / len(sampled)
        baseline_recall = sum(baseline[index] for index in sampled) / len(sampled)
        deltas.append(candidate_recall - baseline_recall)
    deltas.sort()
    return deltas[24], deltas[974]


def _paired_bootstrap_metric_delta(
    truth: list[bool],
    candidate: list[bool],
    baseline: list[bool],
    snapshot_hash: str,
    metric: str,
) -> tuple[float, float]:
    seed = int(hashlib.sha256(f"{snapshot_hash}:{metric}".encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    deltas = []
    for _ in range(1000):
        sampled = [rng.randrange(len(truth)) for _ in truth]
        actual = [truth[index] for index in sampled]
        candidate_predicted = [candidate[index] for index in sampled]
        baseline_predicted = [baseline[index] for index in sampled]
        deltas.append(
            _metrics(actual, candidate_predicted)[metric]
            - _metrics(actual, baseline_predicted)[metric]
        )
    deltas.sort()
    return deltas[24], deltas[974]
