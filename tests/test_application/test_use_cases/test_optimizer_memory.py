from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.use_cases.agent.optimizer_memory import (
    OptimizerMemory,
    scope_key_for,
)
from src.domain.agents.finding import OptimizerInsightStatus

NOW = datetime(2026, 10, 26, tzinfo=UTC)


class FixedClock(Clock):
    def now(self) -> datetime:
        return NOW


class Ids(IdGenerator):
    def __init__(self) -> None:
        self.value = 0

    def new_id(self) -> UUID:
        self.value += 1
        return UUID(int=self.value)


class Findings:
    def __init__(self) -> None:
        self.items = {}

    def create_once(self, finding):
        return self.items.setdefault((finding.session_id, finding.finding_id), finding)


class Insights:
    def __init__(self) -> None:
        self.items = {}

    def create(self, insight):
        self.items[insight.insight_id] = insight
        return insight

    def update(self, insight, expected_rev):
        assert self.items[insight.insight_id].rev == expected_rev
        self.items[insight.insight_id] = replace(insight, rev=expected_rev + 1)
        return self.items[insight.insight_id]

    def list_by_scope(self, scope_key, status, limit=50):
        return [
            item
            for item in self.items.values()
            if item.scope_key == scope_key and item.status == status
        ][:limit]


EVALUATION = {
    "eligible_count": 120,
    "candidate": {"precision": 0.92, "recall": 0.71, "true_positive": 40},
    "baseline": {"precision": 0.9, "recall": 0.6},
}


def _memory():
    findings, insights = Findings(), Insights()
    return (
        OptimizerMemory(
            findings=findings, insights=insights, clock=FixedClock(), ids=Ids()
        ),
        findings,
        insights,
    )


def test_experiment_findings_keep_only_aggregates_and_are_idempotent() -> None:
    memory, findings, _ = _memory()

    first = memory.record_experiment_findings(
        session_id="s1", experiment_id="e1", evaluation=EVALUATION, snapshot_id="snap"
    )
    memory.record_experiment_findings(
        session_id="s1", experiment_id="e1", evaluation=EVALUATION, snapshot_id="snap"
    )

    assert len(findings.items) == 2
    candidate = next(item for item in first if item.dimension_value == "candidate")
    assert candidate.metrics == {"precision": 0.92, "recall": 0.71}
    assert candidate.sample_count == 120
    assert "true_positive" not in candidate.metrics
    assert candidate.opaque_refs == {"experiment_id": "e1", "snapshot_id": "snap"}


def test_insight_needs_the_minimum_support() -> None:
    memory, _, insights = _memory()

    thin = memory.learn(
        area="model",
        statement="x",
        evaluation={**EVALUATION, "eligible_count": 29},
        session_id="s1",
        run_id="r1",
        finding_ids=(),
    )

    assert thin is None
    assert insights.items == {}


def test_new_insight_retires_the_previous_one_for_the_same_scope() -> None:
    memory, _, insights = _memory()
    first = memory.learn(
        area="model",
        statement="XGBoost mejora el recall",
        evaluation=EVALUATION,
        session_id="s1",
        run_id="r1",
        finding_ids=("e1:candidate",),
    )
    second = memory.learn(
        area="model",
        statement="XGBoost mejora el recall más",
        evaluation=EVALUATION,
        session_id="s2",
        run_id="r2",
        finding_ids=("e2:candidate",),
    )

    assert second.supersedes_id == first.insight_id
    assert insights.items[first.insight_id].status is OptimizerInsightStatus.RETIRED
    assert [item.insight_id for item in memory.recall("model")] == [second.insight_id]
    assert second.evidence_summary["candidate_recall"] == 0.71


def test_reevaluation_confirms_refutes_or_marks_stale() -> None:
    for improved, sample, expected in (
        (True, 100, OptimizerInsightStatus.SUPPORTED),
        (False, 100, OptimizerInsightStatus.REFUTED),
        (True, 10, OptimizerInsightStatus.STALE),
    ):
        memory, _, insights = _memory()
        memory.learn(
            area="library",
            statement="s",
            evaluation=EVALUATION,
            session_id="s1",
            run_id="r1",
            finding_ids=(),
        )

        memory.reevaluate("library", improved=improved, sample_count=sample)

        assert [item.status for item in insights.items.values()] == [expected]


def test_scope_is_per_area() -> None:
    memory, _, _ = _memory()
    memory.learn(
        area="model",
        statement="s",
        evaluation=EVALUATION,
        session_id="s1",
        run_id="r1",
        finding_ids=(),
    )

    assert memory.recall("library") == []
    assert scope_key_for("model") == "area:model"


def test_model_area_and_its_specialist_share_one_scope() -> None:
    assert scope_key_for("xgboost") == scope_key_for("model") == "area:model"


def test_published_evaluations_are_remembered_with_their_sample_size() -> None:
    memory, findings, insights = _memory()
    published = {
        "sample": {"eligible_count": 90, "partition": "final"},
        "metrics": {
            "candidate": {"precision": 0.95, "recall": 0.74},
            "baseline": {"precision": 0.93, "recall": 0.6},
        },
    }

    recorded = memory.record_experiment_findings(
        session_id="s1", experiment_id="e9", evaluation=published
    )
    learned = memory.learn(
        area="model",
        statement="x",
        evaluation=published,
        session_id="s1",
        run_id="r1",
        finding_ids=(),
    )

    assert {item.sample_count for item in recorded} == {90}
    assert learned is not None and learned.evidence_summary["candidate_recall"] == 0.74
