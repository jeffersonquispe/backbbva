"""The optimization run: one structure for everything an optimizer session does.

A run holds the optimizer's base configuration, the general insights, every
candidate (hypothesis with its own insights, experiments, results and
conclusion) and, at the top, the winners, the winning configuration and the
strategy. Timelines are not copied inside: the run and each experiment only
reference their `agent_events` stream by key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from src.domain.agents.experiment import AgentExperiment, ComponentVersionReference

# Components an experiment can change; two experiments are independent when they
# change different components and neither depends on the other.
COMPONENT_BY_AREA = {
    "configuration": "configuration",
    "library": "library",
    "vector_store": "vector_store",
    "model": "model",
    "xgboost": "model",
}
COMBINATION_AREA = "combination"


def component_for_area(area: str | None) -> str | None:
    return COMPONENT_BY_AREA.get(area or "")


def experiment_stream_key(run_id: str, experiment_id: str) -> str:
    """`agent_events` partition of one experiment's own timeline."""
    return f"{run_id}#exp#{experiment_id}"


class OptimizationRunConflictError(Exception):
    """The run root changed since it was read (another candidate finished)."""


class OptimizationRunStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RunWinner:
    candidate_id: str
    experiment_id: str
    component: str
    recall: float
    precision: float
    recall_delta: float


@dataclass(frozen=True)
class OptimizationRun:
    """Root node of the run (`RUN`)."""

    run_id: str
    status: OptimizationRunStatus
    created_at: datetime
    updated_at: datetime
    objective_id: str | None = None
    objective_version: int | None = None
    baseline_components: tuple[ComponentVersionReference, ...] = ()
    budget_limits: dict[str, int] = field(default_factory=dict)
    # Optimizer values the run was started with (parallelism, caps, floors).
    optimizer_settings: dict[str, Any] = field(default_factory=dict)
    scope_areas: tuple[str, ...] = ()
    insight_ids: tuple[str, ...] = ()
    memory_insight_ids: tuple[str, ...] = ()
    winners: tuple[RunWinner, ...] = ()
    winning_components: tuple[ComponentVersionReference, ...] = ()
    strategy: dict[str, Any] = field(default_factory=dict)
    # Reference only: the general timeline lives in `agent_events`.
    events_stream: str = ""
    rev: int = 0


@dataclass(frozen=True)
class RunExperimentView:
    experiment: AgentExperiment
    events_stream: str


@dataclass(frozen=True)
class RunCandidateView:
    hypothesis: Any  # AgentHypothesis (application port type)
    experiments: tuple[RunExperimentView, ...] = ()


@dataclass(frozen=True)
class OptimizationRunTree:
    root: OptimizationRun
    candidates: tuple[RunCandidateView, ...] = ()
    unassigned_experiments: tuple[RunExperimentView, ...] = ()
    findings: tuple[Any, ...] = ()  # AgentFinding


@dataclass(frozen=True)
class ExperimentMetrics:
    candidate: dict[str, Any]
    baseline: dict[str, Any]
    eligible_count: int


def experiment_metrics(evaluation: dict[str, Any] | None) -> ExperimentMetrics:
    """Read candidate/baseline metrics from an experiment evaluation.

    The evaluator publishes them under `metrics` (with the sample size in
    `sample.eligible_count`); older records kept them at the top level.
    """
    evaluation = evaluation or {}
    nested = evaluation.get("metrics")
    source: dict[str, Any] = (
        nested if isinstance(nested, dict) and nested.get("candidate") else evaluation
    )
    raw_candidate = source.get("candidate")
    raw_baseline = source.get("baseline")
    candidate: dict[str, Any] = raw_candidate if isinstance(raw_candidate, dict) else {}
    baseline: dict[str, Any] = raw_baseline if isinstance(raw_baseline, dict) else {}
    raw_sample = evaluation.get("sample")
    sample: dict[str, Any] = raw_sample if isinstance(raw_sample, dict) else {}
    eligible = next(
        (
            value
            for value in (
                sample.get("eligible_count"),
                candidate.get("eligible_count"),
                evaluation.get("eligible_count"),
            )
            if isinstance(value, (int, float))
        ),
        0,
    )
    return ExperimentMetrics(dict(candidate), dict(baseline), int(eligible))


def rank_winners(
    candidates: list[tuple[str, AgentExperiment]],
) -> tuple[RunWinner, ...]:
    """Succeeded experiments whose candidate improved recall, best first."""
    winners: list[RunWinner] = []
    for candidate_id, experiment in candidates:
        metrics = experiment_metrics(experiment.global_evaluation)
        candidate, baseline = metrics.candidate, metrics.baseline
        recall = candidate.get("recall")
        precision = candidate.get("precision")
        base_recall = baseline.get("recall")
        if (
            experiment.status.value != "SUCCEEDED"
            or not isinstance(recall, (int, float))
            or not isinstance(precision, (int, float))
            or not isinstance(base_recall, (int, float))
        ):
            continue
        changed = [
            pin.component
            for pin in experiment.components
            if pin not in experiment.baseline_components
        ]
        winners.append(
            RunWinner(
                candidate_id=candidate_id,
                experiment_id=experiment.experiment_id,
                component="+".join(sorted(changed)) or "none",
                recall=float(recall),
                precision=float(precision),
                recall_delta=float(recall) - float(base_recall),
            )
        )
    winners = [item for item in winners if item.recall_delta > 0]
    return tuple(
        sorted(
            winners, key=lambda item: (-item.recall, -item.precision, item.candidate_id)
        )
    )
