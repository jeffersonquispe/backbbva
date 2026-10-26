from datetime import UTC, datetime
from decimal import Decimal

from src.domain.agents.event import AgentEvent, AgentEventKind, AgentEventOutcome
from src.domain.agents.finding import (
    AgentFinding,
    AgentFindingKind,
    OptimizerInsight,
    OptimizerInsightKind,
    OptimizerInsightStatus,
)
from src.infrastructure.persistence.database.dynamodb.repositories.agent_event_repositories import (
    event_from_item,
    event_to_item,
    finding_from_item,
    finding_to_item,
    insight_from_item,
    insight_to_item,
)

NOW = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)


def test_event_round_trips_and_filters_unsafe_refs() -> None:
    event = AgentEvent(
        session_id="s1",
        seq=4,
        event_id="ev",
        occurred_at=NOW,
        kind=AgentEventKind.EXPERIMENT,
        outcome=AgentEventOutcome.FAILED,
        summary="Falló la evaluación",
        reason_code="EVALUATION_FAILED",
        refs={"experiment_id": "e1", "customer_id": "c-1"},
        duration_ms=120,
        expires_at=1_900_000_000,
    )
    item = event_to_item(event)
    assert item["refs"] == {"experiment_id": "e1"}
    assert item["kind"] == "experiment"
    restored = event_from_item({**item, "seq": Decimal(4), "duration_ms": Decimal(120)})
    assert restored.seq == 4
    assert restored.refs == {"experiment_id": "e1"}
    assert restored.outcome is AgentEventOutcome.FAILED
    assert restored.duration_ms == 120


def test_finding_round_trip_keeps_aggregates_only() -> None:
    finding = AgentFinding(
        session_id="s1",
        finding_id="f1",
        kind=AgentFindingKind.DIAGNOSTIC,
        dimension="channel",
        dimension_value="digital",
        sample_count=120,
        metrics={"precision": 0.91, "recall": 0.62},
        source="rollups",
        created_at=NOW,
        period_start="2026-10-01",
        period_end="2026-10-20",
    )
    restored = finding_from_item(finding_to_item(finding))
    assert restored == finding


def test_insight_round_trip_with_status_and_revision() -> None:
    insight = OptimizerInsight(
        insight_id="i1",
        statement="patrón",
        kind=OptimizerInsightKind.PATTERN,
        scope_key="channel:digital",
        status=OptimizerInsightStatus.SUPPORTED,
        sample_count=45,
        created_at=NOW,
        last_evaluated_at=NOW,
        review_after=NOW,
        evidence_summary={"fp_rate": 0.2},
        dataset_snapshot_ids=("snap-1",),
        finding_ids=("f1",),
        rev=2,
    )
    item = insight_to_item(insight)
    assert item["status"] == "SUPPORTED"
    assert insight_from_item(item) == insight
