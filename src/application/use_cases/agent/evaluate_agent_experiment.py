from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from src.application.ports.agent_experiment_evaluator_port import (
    AgentExperimentEvaluator,
)
from src.application.ports.agent_experiment_port import AgentExperimentRepository
from src.application.ports.agent_objective_port import AgentObjectiveRepository
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.dataset_snapshot_port import DatasetSnapshotRepository
from src.domain.agents.experiment import (
    AgentExperiment,
    AgentExperimentKind,
    AgentExperimentStatus,
    ComponentVersionReference,
)
from src.domain.agents.objective import KNOWLEDGE_DECISION_POLICY_EVIDENCE_ONLY_V1
from src.domain.datasets.mature_sample_entities import DatasetSnapshot
from src.domain.datasets.mature_sampling import content_hash

MINIMUM_PROTECTED_SEGMENT_SIZE = 30
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_ALLOWED_COMPONENTS = frozenset({"model", "configuration", "library", "vector_store"})


class AgentExperimentPolicyError(ValueError):
    pass


class EvaluateAgentExperiment:
    def __init__(
        self,
        *,
        experiments: AgentExperimentRepository,
        objectives: AgentObjectiveRepository,
        evaluator: AgentExperimentEvaluator,
        snapshots: DatasetSnapshotRepository,
        datasets: DatasetRepository,
        clock: Clock,
    ) -> None:
        self._experiments = experiments
        self._objectives = objectives
        self._evaluator = evaluator
        self._snapshots = snapshots
        self._datasets = datasets
        self._clock = clock

    def execute(
        self,
        *,
        experiment_id: str,
        session_id: str,
        kind: AgentExperimentKind,
        iteration_number: int,
        components: tuple[ComponentVersionReference, ...],
        baseline_components: tuple[ComponentVersionReference, ...],
        objective_id: str,
        objective_version: int,
    ) -> AgentExperiment:
        if not session_id.strip() or not experiment_id.strip() or iteration_number < 1:
            raise AgentExperimentPolicyError("EXPERIMENT_IDENTITY_INVALID")
        if not objective_id.strip() or objective_version < 1:
            raise AgentExperimentPolicyError("OBJECTIVE_REFERENCE_INVALID")
        self._validate_components(components)
        self._validate_baseline(kind, components, baseline_components)
        objective = self._objectives.get(objective_id, objective_version)
        if objective is None:
            raise AgentExperimentPolicyError("PINNED_OBJECTIVE_NOT_FOUND")
        if (
            objective.knowledge_decision_policy
            != KNOWLEDGE_DECISION_POLICY_EVIDENCE_ONLY_V1
        ):
            raise AgentExperimentPolicyError("KNOWLEDGE_DECISION_POLICY_UNSUPPORTED")
        now = self._clock.now()
        try:
            snapshot, final_rows = self._load_final_snapshot()
            if kind == AgentExperimentKind.COMBINATION:
                self._require_isolated_evidence(
                    session_id,
                    components,
                    baseline_components,
                    objective_id,
                    objective_version,
                )
        except AgentExperimentPolicyError as error:
            code = str(error)
            if not re.fullmatch(r"[A-Z0-9_]+", code):
                code = "GLOBAL_EVALUATION_FAILED"
            return self._experiments.create(
                AgentExperiment(
                    session_id=session_id,
                    experiment_id=experiment_id,
                    iteration_number=iteration_number,
                    kind=kind,
                    status=AgentExperimentStatus.FAILED,
                    components=components,
                    objective_id=objective_id,
                    objective_version=objective_version,
                    created_at=now,
                    baseline_components=baseline_components,
                    completed_at=now,
                    error_code=code,
                )
            )
        running = self._experiments.create(
            AgentExperiment(
                session_id=session_id,
                experiment_id=experiment_id,
                iteration_number=iteration_number,
                kind=kind,
                status=AgentExperimentStatus.RUNNING,
                components=components,
                objective_id=objective_id,
                objective_version=objective_version,
                created_at=now,
                baseline_components=baseline_components,
                snapshot_id=snapshot.snapshot_id,
                snapshot_sha256=snapshot.content_hash,
            )
        )
        try:
            raw_evaluation = self._evaluator.evaluate(
                components=components,
                baseline_components=baseline_components,
                snapshot=snapshot,
                final_rows=final_rows,
                objective_id=objective_id,
                objective_version=objective_version,
            )
            _validate_runner_evidence(
                raw_evaluation,
                components,
                baseline_components,
                objective,
                snapshot_id=snapshot.snapshot_id,
                snapshot_sha256=snapshot.content_hash,
            )
            evaluation, passed = evaluate_global_constraints(objective, raw_evaluation)
        except AgentExperimentPolicyError as error:
            code = str(error)
            if not re.fullmatch(r"[A-Z0-9_]+", code):
                code = "GLOBAL_EVALUATION_FAILED"
            return self._experiments.update(
                replace(
                    running,
                    status=AgentExperimentStatus.FAILED,
                    completed_at=self._clock.now(),
                    error_code=code,
                ),
                expected_status=AgentExperimentStatus.RUNNING.value,
            )
        except ValueError as error:
            # Evaluation adapters may expose a stable, non-sensitive failure
            # code (for example PIPELINE_REPLAY_WORKFLOW_FAILED). Preserve
            # only that restricted form; never persist exception text or data.
            code = str(error)
            if not re.fullmatch(r"[A-Z0-9_]+", code):
                code = "GLOBAL_EVALUATION_FAILED"
            return self._experiments.update(
                replace(
                    running,
                    status=AgentExperimentStatus.FAILED,
                    completed_at=self._clock.now(),
                    error_code=code,
                ),
                expected_status=AgentExperimentStatus.RUNNING.value,
            )
        except Exception:  # noqa: BLE001 - do not persist evaluator payloads/errors
            return self._experiments.update(
                replace(
                    running,
                    status=AgentExperimentStatus.FAILED,
                    completed_at=self._clock.now(),
                    error_code="GLOBAL_EVALUATION_FAILED",
                ),
                expected_status=AgentExperimentStatus.RUNNING.value,
            )
        return self._experiments.update(
            replace(
                running,
                status=(
                    AgentExperimentStatus.SUCCEEDED
                    if passed
                    else AgentExperimentStatus.REJECTED_GLOBAL_CONSTRAINT
                ),
                completed_at=self._clock.now(),
                global_evaluation=evaluation,
            ),
            expected_status=AgentExperimentStatus.RUNNING.value,
        )

    def _validate_components(
        self, components: tuple[ComponentVersionReference, ...]
    ) -> None:
        if not components or len({item.component for item in components}) != len(
            components
        ):
            raise AgentExperimentPolicyError("COMPONENT_SET_INVALID")
        for item in components:
            if (
                item.component not in _ALLOWED_COMPONENTS
                or not item.entity_id.strip()
                or not item.version.strip()
                or not _SHA256_PATTERN.fullmatch(item.content_sha256)
            ):
                raise AgentExperimentPolicyError("COMPONENT_REFERENCE_INVALID")

    def _load_final_snapshot(self) -> tuple[DatasetSnapshot, list[dict[str, Any]]]:
        for listed in self._snapshots.list_recent(50):
            maturing_days = listed.specification.get("maturing_days")
            if (
                "final" not in listed.dataset_refs
                or "all" not in listed.dataset_refs
                or not isinstance(listed.specification.get("as_of"), str)
                or listed.specification.get("content_hash_format")
                != "persisted_csv_rows_v1"
                or not isinstance(maturing_days, int)
                or maturing_days < 0
            ):
                continue
            snapshot = self._snapshots.get(listed.snapshot_id)
            if (
                snapshot is None
                or snapshot.content_hash != listed.content_hash
                or not _SHA256_PATTERN.fullmatch(snapshot.content_hash)
                or "final" not in snapshot.dataset_refs
                or "all" not in snapshot.dataset_refs
                or "final" not in snapshot.partition_counts
            ):
                continue
            try:
                partitions = {
                    name: self._datasets.get_rows(snapshot.dataset_refs[name])
                    for name in ("training", "validation", "test", "final")
                }
                all_rows = self._datasets.get_rows(snapshot.dataset_refs["all"])
            except Exception:  # noqa: BLE001 - fail closed on missing sample data
                continue
            if any(
                len(partitions[name]) != snapshot.partition_counts.get(name)
                for name in ("training", "validation", "test", "final")
            ) or len(all_rows) != sum(
                snapshot.partition_counts.get(name, 0)
                for name in ("training", "validation", "test")
            ):
                continue
            if content_hash({**partitions, "all": all_rows}) != snapshot.content_hash:
                continue
            if not partitions["final"]:
                continue
            return snapshot, partitions["final"]
        raise AgentExperimentPolicyError("FINAL_MATURE_SNAPSHOT_UNAVAILABLE")

    def _validate_baseline(
        self,
        kind: AgentExperimentKind,
        components: tuple[ComponentVersionReference, ...],
        baseline_components: tuple[ComponentVersionReference, ...],
    ) -> None:
        if not baseline_components:
            raise AgentExperimentPolicyError("BASELINE_COMPONENTS_REQUIRED")
        if len({item.component for item in baseline_components}) != len(
            baseline_components
        ):
            raise AgentExperimentPolicyError("BASELINE_COMPONENT_SET_INVALID")
        candidate_by_type = {item.component: item for item in components}
        baseline_by_type = {item.component: item for item in baseline_components}
        if set(candidate_by_type) != set(baseline_by_type):
            raise AgentExperimentPolicyError("BASELINE_COMPONENT_SET_MISMATCH")
        for item in baseline_components:
            if (
                item.component not in _ALLOWED_COMPONENTS
                or not item.entity_id.strip()
                or not item.version.strip()
                or not _SHA256_PATTERN.fullmatch(item.content_sha256)
            ):
                raise AgentExperimentPolicyError("BASELINE_COMPONENT_REFERENCE_INVALID")
        changed = sum(
            candidate_by_type[component] != baseline_by_type[component]
            for component in candidate_by_type
        )
        if changed == 0:
            raise AgentExperimentPolicyError("EXPERIMENT_HAS_NO_COMPONENT_CHANGE")
        if kind == AgentExperimentKind.ISOLATED and changed != 1:
            raise AgentExperimentPolicyError(
                "ISOLATED_EXPERIMENT_REQUIRES_ONE_COMPONENT"
            )
        if kind == AgentExperimentKind.COMBINATION and changed < 2:
            raise AgentExperimentPolicyError("COMBINATION_REQUIRES_MULTIPLE_COMPONENTS")

    def _require_isolated_evidence(
        self,
        session_id: str,
        components: tuple[ComponentVersionReference, ...],
        baseline_components: tuple[ComponentVersionReference, ...],
        objective_id: str,
        objective_version: int,
    ) -> None:
        prior = self._experiments.list_for_session(session_id)
        isolated_refs = set()
        for item in prior:
            if (
                item.kind != AgentExperimentKind.ISOLATED
                or item.status != AgentExperimentStatus.SUCCEEDED
                or item.objective_id != objective_id
                or item.objective_version != objective_version
                or len(item.components) != len(item.baseline_components)
            ):
                continue
            item_candidates = {ref.component: ref for ref in item.components}
            item_baselines = {ref.component: ref for ref in item.baseline_components}
            differences = [
                (component, candidate, item_baselines[component])
                for component, candidate in item_candidates.items()
                if component in item_baselines
                and candidate != item_baselines[component]
            ]
            if len(differences) == 1:
                isolated_refs.add(differences[0])
        candidate_by_type = {item.component: item for item in components}
        baseline_by_type = {item.component: item for item in baseline_components}
        changed = [
            (component, candidate, baseline_by_type[component])
            for component, candidate in candidate_by_type.items()
            if candidate != baseline_by_type[component]
        ]
        if any(reference not in isolated_refs for reference in changed):
            raise AgentExperimentPolicyError("ISOLATED_EVIDENCE_REQUIRED")


def evaluate_global_constraints(
    objective: Any, raw: dict[str, Any]
) -> tuple[dict[str, Any], bool]:
    """Validate pipeline aggregates and redact under-supported segment metrics."""
    global_metrics = raw.get("global")
    baseline_metrics = raw.get("baseline_global")
    segments = raw.get("segments")
    if (
        not isinstance(global_metrics, dict)
        or not isinstance(baseline_metrics, dict)
        or not isinstance(segments, dict)
    ):
        raise AgentExperimentPolicyError("GLOBAL_EVIDENCE_INVALID")
    eligible = _count(global_metrics.get("eligible_count"))
    positive_support = _count(global_metrics.get("positive_support"))
    coverage = _finite_number(global_metrics.get("mature_label_coverage_pct"))
    precision = _finite_number(global_metrics.get("precision"))
    publication_minimum = max(
        MINIMUM_PROTECTED_SEGMENT_SIZE,
        objective.minimum_count_to_publish_aggregates,
    )
    published = eligible >= publication_minimum
    constraints: list[dict[str, Any]] = []
    constraints.append(
        _constraint(
            "minimum_global_support",
            eligible >= objective.minimum_global_support,
            eligible if eligible >= MINIMUM_PROTECTED_SEGMENT_SIZE else None,
            objective.minimum_global_support,
        )
    )
    for metric_name in objective.primary_metrics:
        candidate_value = _finite_number(global_metrics.get(metric_name))
        baseline_value = _finite_number(baseline_metrics.get(metric_name))
        delta = (
            round(candidate_value - baseline_value, 8)
            if candidate_value is not None and baseline_value is not None
            else None
        )
        constraints.append(
            _constraint(
                f"global_primary_metric_non_regression:{metric_name}",
                delta is not None and delta >= 0,
                delta if published else None,
                0,
            )
        )
    constraints.append(
        _constraint(
            "aggregate_publication_threshold",
            published,
            eligible if published else None,
            publication_minimum,
        )
    )
    constraints.append(
        _constraint(
            "minimum_mature_alert_coverage_pct",
            coverage is not None
            and coverage >= objective.minimum_mature_alert_coverage_pct,
            coverage if published else None,
            objective.minimum_mature_alert_coverage_pct,
        )
    )
    constraints.append(
        _constraint(
            "global_precision_floor",
            precision is not None and precision >= objective.precision_floor,
            precision if published else None,
            objective.precision_floor,
        )
    )
    protected_segments: dict[str, dict[str, Any]] = {}
    minimum_segment = max(
        MINIMUM_PROTECTED_SEGMENT_SIZE, objective.minimum_support_per_segment
    )
    for segment_name, metrics in sorted(segments.items()):
        if not isinstance(segment_name, str) or not isinstance(metrics, dict):
            raise AgentExperimentPolicyError("SEGMENT_EVIDENCE_INVALID")
        support = _count(metrics.get("support"))
        if support < minimum_segment:
            continue
        segment_precision = _finite_number(metrics.get("precision"))
        protected_segments[_safe_segment_name(segment_name)] = {
            "support": support,
            "candidate": {
                "precision": segment_precision,
                "recall": _finite_number(metrics.get("recall")),
            },
            "baseline": {
                "precision": _finite_number(metrics.get("baseline_precision")),
                "recall": _finite_number(metrics.get("baseline_recall")),
            },
            "delta": {
                "precision": metrics["delta_precision"],
                "recall": metrics["delta_recall"],
            },
        }
        constraints.append(
            _constraint(
                f"segment_precision:{_safe_segment_name(segment_name)}",
                segment_precision is not None
                and segment_precision >= objective.precision_floor,
                segment_precision,
                objective.precision_floor,
            )
        )
    protected_global = {
        "support": eligible if published else None,
        "positive_support": (
            positive_support
            if published and positive_support >= MINIMUM_PROTECTED_SEGMENT_SIZE
            else None
        ),
        "eligible_count": eligible if published else None,
        "precision": precision if published else None,
        "recall": _finite_number(global_metrics.get("recall")) if published else None,
        "mature_label_coverage_pct": coverage if published else None,
    }
    sample = raw["sample"]
    deltas = raw["delta"]
    passed = all(item["status"] == "PASSED" for item in constraints)
    return (
        {
            "status": "PASSED" if passed else "REJECTED_GLOBAL_CONSTRAINT",
            "sample": {
                "snapshot_id": sample["snapshot_id"],
                "content_sha256": sample["content_sha256"],
                "partition": "final",
                "eligible_count": eligible if published else None,
                "mature_coverage_pct": coverage if published else None,
            },
            "metrics": {
                "candidate": protected_global,
                "baseline": {
                    metric_name: _finite_number(baseline_metrics.get(metric_name))
                    if published
                    else None
                    for metric_name in objective.primary_metrics
                },
            },
            "delta": {
                metric_name: {
                    "estimate": deltas[metric_name]["estimate"] if published else None,
                    "ci95_lower": deltas[metric_name]["ci95_lower"]
                    if published
                    else None,
                    "ci95_upper": deltas[metric_name]["ci95_upper"]
                    if published
                    else None,
                }
                for metric_name in objective.primary_metrics
            },
            "uncertainty": {
                "method": "paired_bootstrap",
                "confidence_level": 0.95,
                "resamples": raw["uncertainty"]["resamples"],
            },
            "knowledge_evidence": raw["knowledge_evidence"],
            "minimum_protected_segment_size": minimum_segment,
            "global": protected_global,
            "baseline_global": {
                metric_name: _finite_number(baseline_metrics.get(metric_name))
                if published
                else None
                for metric_name in objective.primary_metrics
            },
            "segments": protected_segments,
            "constraints": constraints,
        },
        passed,
    )


def _validate_runner_evidence(
    raw: dict[str, Any],
    components: tuple[ComponentVersionReference, ...],
    baseline_components: tuple[ComponentVersionReference, ...],
    objective: Any,
    *,
    snapshot_id: str,
    snapshot_sha256: str,
) -> None:
    """Reject aggregate-only or mismatched runner output before success."""
    sample = raw.get("sample")
    uncertainty = raw.get("uncertainty")
    delta = raw.get("delta")
    knowledge_evidence = raw.get("knowledge_evidence")
    baseline_sample = raw.get("baseline_sample")
    candidate_sample = raw.get("candidate_sample")
    if (
        not isinstance(sample, dict)
        or not isinstance(sample.get("snapshot_id"), str)
        or not sample["snapshot_id"].strip()
        or not isinstance(sample.get("content_sha256"), str)
        or not _SHA256_PATTERN.fullmatch(sample["content_sha256"])
        or sample.get("partition") != "final"
        or sample.get("snapshot_id") != snapshot_id
        or sample.get("content_sha256") != snapshot_sha256
        or baseline_sample != sample
        or candidate_sample != sample
        or raw.get("evaluated_components") != _reference_payload(components)
        or raw.get("evaluated_baseline_components")
        != _reference_payload(baseline_components)
        or not isinstance(uncertainty, dict)
        or uncertainty.get("method") != "paired_bootstrap"
        or uncertainty.get("confidence_level") != 0.95
        or not isinstance(uncertainty.get("resamples"), int)
        or uncertainty["resamples"] < 100
        or not isinstance(delta, dict)
        or not isinstance(knowledge_evidence, dict)
        or knowledge_evidence.get("decision_policy")
        != objective.knowledge_decision_policy
        or not isinstance(knowledge_evidence.get("candidate_asset_count"), int)
        or isinstance(knowledge_evidence.get("candidate_asset_count"), bool)
        or knowledge_evidence.get("candidate_asset_count", -1) < 0
        or not isinstance(knowledge_evidence.get("baseline_asset_count"), int)
        or isinstance(knowledge_evidence.get("baseline_asset_count"), bool)
        or knowledge_evidence.get("baseline_asset_count", -1) < 0
    ):
        raise AgentExperimentPolicyError("GLOBAL_EVIDENCE_INVALID")
    candidate = raw.get("global")
    baseline = raw.get("baseline_global")
    if not isinstance(candidate, dict) or not isinstance(baseline, dict):
        raise AgentExperimentPolicyError("GLOBAL_EVIDENCE_INVALID")
    for metric_name in objective.primary_metrics:
        interval = delta.get(metric_name)
        candidate_value = _finite_number(candidate.get(metric_name))
        baseline_value = _finite_number(baseline.get(metric_name))
        if not isinstance(interval, dict):
            raise AgentExperimentPolicyError("GLOBAL_EVIDENCE_INVALID")
        estimate = _finite_number(interval.get("estimate"))
        lower = _finite_number(interval.get("ci95_lower"))
        upper = _finite_number(interval.get("ci95_upper"))
        if (
            candidate_value is None
            or baseline_value is None
            or estimate is None
            or lower is None
            or upper is None
            or lower > estimate
            or estimate > upper
            or abs(estimate - (candidate_value - baseline_value)) > 1e-6
        ):
            raise AgentExperimentPolicyError("GLOBAL_EVIDENCE_INVALID")
    segment_evidence = raw.get("segments")
    if not isinstance(segment_evidence, dict):
        raise AgentExperimentPolicyError("GLOBAL_EVIDENCE_INVALID")
    protected_minimum = max(
        MINIMUM_PROTECTED_SEGMENT_SIZE,
        objective.minimum_support_per_segment,
    )
    for segment_name, metrics in segment_evidence.items():
        if not isinstance(segment_name, str) or not isinstance(metrics, dict):
            raise AgentExperimentPolicyError("SEGMENT_EVIDENCE_INVALID")
        support = _count(metrics.get("support"))
        if support < protected_minimum:
            continue
        _safe_segment_name(segment_name)
        for metric_name in ("precision", "recall"):
            candidate_value = _finite_number(metrics.get(metric_name))
            baseline_value = _finite_number(metrics.get(f"baseline_{metric_name}"))
            interval = metrics.get(f"delta_{metric_name}")
            if not isinstance(interval, dict):
                raise AgentExperimentPolicyError("SEGMENT_EVIDENCE_INVALID")
            estimate = _finite_number(interval.get("estimate"))
            lower = _finite_number(interval.get("ci95_lower"))
            upper = _finite_number(interval.get("ci95_upper"))
            if (
                candidate_value is None
                or baseline_value is None
                or estimate is None
                or lower is None
                or upper is None
                or lower > estimate
                or estimate > upper
                or abs(estimate - (candidate_value - baseline_value)) > 1e-6
            ):
                raise AgentExperimentPolicyError("SEGMENT_EVIDENCE_INVALID")


def _reference_payload(
    references: tuple[ComponentVersionReference, ...],
) -> list[dict[str, str]]:
    return [
        {
            "component": item.component,
            "entity_id": item.entity_id,
            "version": item.version,
            "content_sha256": item.content_sha256,
        }
        for item in references
    ]


def _constraint(
    name: str,
    passed: bool,
    aggregate: Any,
    minimum_sample_size: int | float,
) -> dict[str, Any]:
    return {
        "constraint_id": name,
        "status": "PASSED" if passed else "FAILED",
        "aggregate": aggregate,
        "minimum_sample_size": minimum_sample_size,
    }


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentExperimentPolicyError("AGGREGATE_COUNT_INVALID")
    return value


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _safe_segment_name(value: str) -> str:
    # Segment keys are contract labels, not values derived from cases.
    if len(value) > 64 or not value.replace("_", "").replace("-", "").isalnum():
        raise AgentExperimentPolicyError("SEGMENT_LABEL_INVALID")
    return value
