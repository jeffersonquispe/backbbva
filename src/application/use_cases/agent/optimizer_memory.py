"""Findings of one session and the data-backed memory shared across sessions.

Nothing here stores rows, customer ids or amounts: findings carry aggregates
with their sample size, and an insight is only published when its segment has
at least `MIN_SUPPORT` cases. Persisting an insight never approves a change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from src.application.ports.agent_finding_port import AgentFindingRepository
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.optimizer_insight_port import OptimizerInsightRepository
from src.domain.agents.finding import (
    MIN_SUPPORT,
    AgentFinding,
    AgentFindingKind,
    OptimizerInsight,
    OptimizerInsightKind,
    OptimizerInsightStatus,
)

REVIEW_AFTER_DAYS = 30
FINDING_RETENTION_DAYS = 730
_METRICS = ("precision", "recall")


# Sessions scope the model area as "model"; its specialist is called "xgboost".
_AREA_BY_SPECIALIST = {"xgboost": "model"}


def scope_key_for(area: str) -> str:
    return f"area:{_AREA_BY_SPECIALIST.get(area, area)}"


class OptimizerMemory:
    def __init__(
        self,
        *,
        findings: AgentFindingRepository,
        insights: OptimizerInsightRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._findings = findings
        self._insights = insights
        self._clock = clock
        self._ids = ids

    def record_experiment_findings(
        self,
        *,
        session_id: str,
        experiment_id: str,
        evaluation: Mapping[str, Any],
        snapshot_id: str | None = None,
    ) -> list[AgentFinding]:
        """One aggregate finding per side (candidate/baseline) of an experiment."""
        support = int(evaluation.get("eligible_count") or 0)
        now = self._clock.now()
        recorded: list[AgentFinding] = []
        for side in ("candidate", "baseline"):
            metrics = evaluation.get(side)
            if not isinstance(metrics, Mapping):
                continue
            refs = {"experiment_id": experiment_id}
            if snapshot_id:
                refs["snapshot_id"] = snapshot_id
            recorded.append(
                self._findings.create_once(
                    AgentFinding(
                        session_id=session_id,
                        # Stable id: replaying the same experiment never duplicates.
                        finding_id=f"{experiment_id}:{side}",
                        kind=AgentFindingKind.DIAGNOSTIC,
                        dimension="pipeline",
                        dimension_value=side,
                        sample_count=support,
                        metrics={
                            key: float(metrics[key])
                            for key in _METRICS
                            if isinstance(metrics.get(key), (int, float))
                        },
                        source="global_evaluation",
                        created_at=now,
                        opaque_refs=refs,
                        expires_at=int(
                            (now + timedelta(days=FINDING_RETENTION_DAYS)).timestamp()
                        ),
                    )
                )
            )
        return recorded

    def learn(
        self,
        *,
        area: str,
        statement: str,
        evaluation: Mapping[str, Any],
        session_id: str,
        run_id: str | None,
        finding_ids: tuple[str, ...],
        snapshot_ids: tuple[str, ...] = (),
    ) -> OptimizerInsight | None:
        """Publish a supported insight; refuse thin evidence."""
        support = int(evaluation.get("eligible_count") or 0)
        if support < MIN_SUPPORT:
            return None
        now = self._clock.now()
        candidate = evaluation.get("candidate") or {}
        baseline = evaluation.get("baseline") or {}
        summary = {
            f"{side}_{metric}": float(source[metric])
            for side, source in (("candidate", candidate), ("baseline", baseline))
            for metric in _METRICS
            if isinstance(source.get(metric), (int, float))
        }
        scope_key = scope_key_for(area)
        previous = self._insights.list_by_scope(
            scope_key, OptimizerInsightStatus.SUPPORTED
        )
        insight = OptimizerInsight(
            insight_id=str(self._ids.new_id()),
            statement=statement[:300],
            kind=OptimizerInsightKind.PATTERN,
            scope_key=scope_key,
            status=OptimizerInsightStatus.SUPPORTED,
            sample_count=support,
            created_at=now,
            last_evaluated_at=now,
            review_after=now + timedelta(days=REVIEW_AFTER_DAYS),
            evidence_summary=summary,
            dataset_snapshot_ids=snapshot_ids,
            finding_ids=finding_ids,
            origin_session_id=session_id,
            origin_run_id=run_id,
            supersedes_id=previous[0].insight_id if previous else None,
        )
        created = self._insights.create(insight)
        for old in previous:
            self._insights.update(
                replace(
                    old, status=OptimizerInsightStatus.RETIRED, last_evaluated_at=now
                ),
                expected_rev=old.rev,
            )
        return created

    def recall(self, area: str, limit: int = 5) -> list[OptimizerInsight]:
        """Data-backed context for a new session on the same segment."""
        return self._insights.list_by_scope(
            scope_key_for(area), OptimizerInsightStatus.SUPPORTED, limit
        )

    def reevaluate(
        self,
        area: str,
        *,
        improved: bool,
        sample_count: int,
        now: datetime | None = None,
    ) -> list[OptimizerInsight]:
        """Re-check supported insights of a segment against fresh evidence.

        Contradicting evidence refutes the insight; a sample too small to
        compare marks it stale; confirming evidence renews its review date.
        """
        moment = now or self._clock.now()
        updated: list[OptimizerInsight] = []
        for insight in self.recall(area, limit=50):
            if sample_count < MIN_SUPPORT:
                status = OptimizerInsightStatus.STALE
            elif improved:
                status = OptimizerInsightStatus.SUPPORTED
            else:
                status = OptimizerInsightStatus.REFUTED
            review_after = (
                moment + timedelta(days=REVIEW_AFTER_DAYS)
                if status is OptimizerInsightStatus.SUPPORTED
                else insight.review_after
            )
            updated.append(
                self._insights.update(
                    replace(
                        insight,
                        status=status,
                        last_evaluated_at=moment,
                        review_after=review_after,
                    ),
                    expected_rev=insight.rev,
                )
            )
        return updated
