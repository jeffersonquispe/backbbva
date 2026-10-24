from __future__ import annotations

import hashlib
import random
import re
from typing import Any

from src.application.ports.agent_experiment_component_port import (
    AgentExperimentComponentResolver,
    ResolvedAgentComponent,
)
from src.application.ports.agent_experiment_evaluator_port import (
    AgentExperimentEvaluator,
)
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.agent_pipeline_scorer_port import (
    AgentPipelineScore,
    AgentPipelineScorer,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.datasets.mature_sample_entities import DatasetSnapshot

BOOTSTRAP_RESAMPLES = 1000
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class PairedAgentExperimentRunner(AgentExperimentEvaluator):
    """Resolve and execute exact candidate/baseline stacks on one final sample."""

    def __init__(
        self,
        *,
        components: AgentExperimentComponentResolver,
        scorer: AgentPipelineScorer,
        objectives: AgentObjectiveRepository,
    ) -> None:
        self._components = components
        self._scorer = scorer
        self._objectives = objectives

    def evaluate(
        self,
        *,
        components: tuple[ComponentVersionReference, ...],
        baseline_components: tuple[ComponentVersionReference, ...],
        snapshot: DatasetSnapshot,
        final_rows: list[dict[str, Any]],
        objective_id: str,
        objective_version: int,
    ) -> dict[str, Any]:
        maturing_days = snapshot.specification.get("maturing_days")
        if (
            "final" not in snapshot.dataset_refs
            or not isinstance(snapshot.specification.get("as_of"), str)
            or not isinstance(maturing_days, int)
            or maturing_days < 0
            or not _SHA256_PATTERN.fullmatch(snapshot.content_hash)
            or not final_rows
        ):
            raise ValueError("FINAL_MATURE_SNAPSHOT_INVALID")
        objective = self._objectives.get(objective_id, objective_version)
        if objective is None:
            raise ValueError("PINNED_OBJECTIVE_NOT_FOUND")
        candidate = self._resolve(components)
        baseline = self._resolve(baseline_components)
        candidate_result = self._scorer.predict_positive(
            candidate, final_rows, snapshot=snapshot
        )
        baseline_result = self._scorer.predict_positive(
            baseline, final_rows, snapshot=snapshot
        )
        # A long replay must not silently span mutable component changes.
        self._assert_pins_unchanged(components)
        self._assert_pins_unchanged(baseline_components)
        candidate_predictions, candidate_evidence, candidate_undecided = _scorer_result(
            candidate_result
        )
        baseline_predictions, baseline_evidence, baseline_undecided = _scorer_result(
            baseline_result
        )
        if len(candidate_predictions) != len(final_rows) or len(
            baseline_predictions
        ) != len(final_rows):
            raise ValueError("SCORER_RESULT_LENGTH_INVALID")

        labels = [row.get(objective.success_label) for row in final_rows]
        eligible_indices = [
            index
            for index, label in enumerate(labels)
            if label in {objective.positive_label, objective.negative_label}
        ]
        if not eligible_indices:
            raise ValueError("FINAL_SAMPLE_HAS_NO_ELIGIBLE_LABELS")
        truth = [
            labels[index] == objective.positive_label for index in eligible_indices
        ]
        candidate_values = [candidate_predictions[index] for index in eligible_indices]
        baseline_values = [baseline_predictions[index] for index in eligible_indices]
        candidate_metrics = _metrics(truth, candidate_values)
        baseline_metrics = _metrics(truth, baseline_values)
        delta = {
            metric: _paired_bootstrap_delta(
                truth,
                candidate_values,
                baseline_values,
                snapshot.content_hash,
                metric,
            )
            for metric in objective.primary_metrics
        }
        support = sum(truth)
        coverage = 100 * len(eligible_indices) / max(1, len(final_rows))
        candidate_global = {
            **candidate_metrics,
            "eligible_count": len(eligible_indices),
            "positive_support": support,
            "mature_label_coverage_pct": round(coverage, 4),
            "undecided_count": candidate_undecided,
            "decision_coverage_pct": round(
                100 * (len(final_rows) - candidate_undecided) / max(1, len(final_rows)),
                4,
            ),
        }
        baseline_global = {
            **baseline_metrics,
            "eligible_count": len(eligible_indices),
            "positive_support": support,
            "mature_label_coverage_pct": round(coverage, 4),
            "undecided_count": baseline_undecided,
            "decision_coverage_pct": round(
                100 * (len(final_rows) - baseline_undecided) / max(1, len(final_rows)),
                4,
            ),
        }
        sample = {
            "snapshot_id": snapshot.snapshot_id,
            "content_sha256": snapshot.content_hash,
            "partition": "final",
        }
        return {
            "sample": sample,
            "baseline_sample": sample,
            "candidate_sample": sample,
            "evaluated_components": _pin_payload(components),
            "evaluated_baseline_components": _pin_payload(baseline_components),
            "global": candidate_global,
            "baseline_global": baseline_global,
            "segments": _protected_segments(
                objective,
                final_rows,
                eligible_indices,
                truth,
                candidate_values,
                baseline_values,
                snapshot.content_hash,
            ),
            "delta": {
                name: {
                    "estimate": round(
                        candidate_metrics[name] - baseline_metrics[name], 8
                    ),
                    "ci95_lower": interval[0],
                    "ci95_upper": interval[1],
                }
                for name, interval in delta.items()
            },
            "uncertainty": {
                "method": "paired_bootstrap",
                "confidence_level": 0.95,
                "resamples": BOOTSTRAP_RESAMPLES,
            },
            "knowledge_evidence": {
                "decision_policy": objective.knowledge_decision_policy,
                "candidate_asset_count": candidate_evidence,
                "baseline_asset_count": baseline_evidence,
            },
        }

    def _assert_pins_unchanged(
        self, references: tuple[ComponentVersionReference, ...]
    ) -> None:
        for reference in references:
            resolved = self._components.resolve(reference)
            if resolved is None or resolved.reference != reference:
                raise ValueError("COMPONENT_PIN_CHANGED_DURING_EVALUATION")
            actual = ComponentVersionReference.pin(
                reference.component,
                reference.entity_id,
                reference.version,
                resolved.content,
            )
            if actual.content_sha256 != reference.content_sha256:
                raise ValueError("COMPONENT_PIN_CHANGED_DURING_EVALUATION")

    def _resolve(
        self, references: tuple[ComponentVersionReference, ...]
    ) -> tuple[ResolvedAgentComponent, ...]:
        resolved: list[ResolvedAgentComponent] = []
        for reference in references:
            item = self._components.resolve(reference)
            if item is None or item.reference != reference:
                raise ValueError("COMPONENT_PIN_UNRESOLVED")
            actual = ComponentVersionReference.pin(
                reference.component,
                reference.entity_id,
                reference.version,
                item.content,
            )
            if actual.content_sha256 != reference.content_sha256:
                raise ValueError("COMPONENT_PIN_HASH_MISMATCH")
            resolved.append(item)
        return tuple(resolved)


def _metrics(truth: list[bool], predicted: list[bool]) -> dict[str, float | int]:
    tp = sum(actual and guess for actual, guess in zip(truth, predicted))
    fp = sum((not actual) and guess for actual, guess in zip(truth, predicted))
    fn = sum(actual and (not guess) for actual, guess in zip(truth, predicted))
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {
        "precision": round(precision, 8),
        "recall": round(recall, 8),
        "f1": round(2 * precision * recall / max(1e-12, precision + recall), 8),
        "support": len(truth),
    }


def _scorer_result(
    result: list[bool] | AgentPipelineScore,
) -> tuple[list[bool], int, int]:
    if isinstance(result, AgentPipelineScore):
        if (
            isinstance(result.knowledge_evidence_asset_count, bool)
            or result.knowledge_evidence_asset_count < 0
        ):
            raise ValueError("SCORER_EVIDENCE_COUNT_INVALID")
        if (
            isinstance(result.undecided_count, bool)
            or result.undecided_count < 0
            or result.undecided_count > len(result.predictions)
        ):
            raise ValueError("SCORER_UNDECIDED_COUNT_INVALID")
        return (
            result.predictions,
            result.knowledge_evidence_asset_count,
            result.undecided_count,
        )
    return result, 0, 0


def _paired_bootstrap_delta(
    truth: list[bool],
    candidate: list[bool],
    baseline: list[bool],
    snapshot_hash: str,
    metric: str,
) -> tuple[float, float]:
    seed = int(
        hashlib.sha256(f"{snapshot_hash}:{metric}".encode()).hexdigest()[:16], 16
    )
    rng = random.Random(seed)
    deltas: list[float] = []
    count = len(truth)
    for _ in range(BOOTSTRAP_RESAMPLES):
        indices = [rng.randrange(count) for _ in range(count)]
        actual = [truth[index] for index in indices]
        candidate_sample = [candidate[index] for index in indices]
        baseline_sample = [baseline[index] for index in indices]
        deltas.append(
            float(_metrics(actual, candidate_sample)[metric])
            - float(_metrics(actual, baseline_sample)[metric])
        )
    deltas.sort()
    return round(deltas[24], 8), round(deltas[974], 8)


def _protected_segments(
    objective: Any,
    rows: list[dict[str, Any]],
    eligible_indices: list[int],
    truth: list[bool],
    candidate: list[bool],
    baseline: list[bool],
    snapshot_hash: str,
) -> dict[str, dict[str, Any]]:
    """Only use allow-listed objective segments; omit low-support labels."""
    configured = objective.schema_mapping.get("protected_segments", {})
    if not isinstance(configured, dict):
        return {}
    minimum = max(30, objective.minimum_support_per_segment)
    output: dict[str, dict[str, Any]] = {}
    for field, allowed_values in sorted(configured.items()):
        if (
            not isinstance(field, str)
            or not isinstance(allowed_values, list)
            or not all(isinstance(value, str) for value in allowed_values)
        ):
            continue
        for value in allowed_values:
            selected = [
                offset
                for offset, index in enumerate(eligible_indices)
                if rows[index].get(field) == value
            ]
            if len(selected) < minimum:
                continue
            key = f"{field}_{value}"
            if len(key) > 64 or not key.replace("_", "").replace("-", "").isalnum():
                continue
            segment_truth = [truth[index] for index in selected]
            candidate_segment = [candidate[index] for index in selected]
            baseline_segment = [baseline[index] for index in selected]
            candidate_metrics = _metrics(segment_truth, candidate_segment)
            baseline_metrics = _metrics(segment_truth, baseline_segment)
            segment_delta = {
                metric: _paired_bootstrap_delta(
                    segment_truth,
                    candidate_segment,
                    baseline_segment,
                    f"{snapshot_hash}:{key}",
                    metric,
                )
                for metric in ("precision", "recall")
            }
            output[key] = {
                "support": len(selected),
                "precision": candidate_metrics["precision"],
                "recall": candidate_metrics["recall"],
                "baseline_precision": baseline_metrics["precision"],
                "baseline_recall": baseline_metrics["recall"],
                "delta_precision": {
                    "estimate": round(
                        float(candidate_metrics["precision"])
                        - float(baseline_metrics["precision"]),
                        8,
                    ),
                    "ci95_lower": segment_delta["precision"][0],
                    "ci95_upper": segment_delta["precision"][1],
                },
                "delta_recall": {
                    "estimate": round(
                        float(candidate_metrics["recall"])
                        - float(baseline_metrics["recall"]),
                        8,
                    ),
                    "ci95_lower": segment_delta["recall"][0],
                    "ci95_upper": segment_delta["recall"][1],
                },
            }
    return output


def _pin_payload(
    references: tuple[ComponentVersionReference, ...],
) -> list[dict[str, str]]:
    return [
        {
            "component": ref.component,
            "entity_id": ref.entity_id,
            "version": ref.version,
            "content_sha256": ref.content_sha256,
        }
        for ref in references
    ]
