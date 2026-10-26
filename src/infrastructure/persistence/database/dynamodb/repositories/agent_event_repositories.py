from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.application.ports.agent_event_port import AgentEventRepository
from src.application.ports.agent_finding_port import AgentFindingRepository
from src.application.ports.optimizer_insight_port import OptimizerInsightRepository
from src.domain.agents.event import (
    AgentEvent,
    AgentEventKind,
    AgentEventOutcome,
    safe_refs,
)
from src.domain.agents.finding import (
    AgentFinding,
    AgentFindingKind,
    OptimizerInsight,
    OptimizerInsightKind,
    OptimizerInsightStatus,
)
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)
from src.infrastructure.persistence.database.dynamodb.serialization import (
    from_dynamodb,
    to_dynamodb,
)

MAX_APPEND_ATTEMPTS = 8


class AgentEventConflictError(Exception):
    """A concurrent writer kept winning the next `seq`."""


def event_to_item(event: AgentEvent) -> dict[str, Any]:
    item: dict[str, Any] = {
        "session_id": event.session_id,
        "seq": event.seq,
        "event_id": event.event_id,
        "occurred_at": event.occurred_at.isoformat(),
        "kind": event.kind.value,
        "outcome": event.outcome.value,
        "summary": event.summary,
        "reason_code": event.reason_code,
        "refs": safe_refs(event.refs),
        "duration_ms": event.duration_ms,
        "cost_micros": event.cost_micros,
        "actor_id": event.actor_id,
        "expires_at": event.expires_at,
    }
    return to_dynamodb({key: value for key, value in item.items() if value is not None})


def event_from_item(item: dict[str, Any]) -> AgentEvent:
    data = from_dynamodb(item)
    return AgentEvent(
        session_id=data["session_id"],
        seq=int(data["seq"]),
        event_id=data["event_id"],
        occurred_at=datetime.fromisoformat(data["occurred_at"]),
        kind=AgentEventKind(data["kind"]),
        outcome=AgentEventOutcome(data["outcome"]),
        summary=data.get("summary", ""),
        reason_code=data.get("reason_code"),
        refs=dict(data.get("refs", {})),
        duration_ms=data.get("duration_ms"),
        cost_micros=data.get("cost_micros"),
        actor_id=data.get("actor_id"),
        expires_at=data.get("expires_at"),
    )


class DynamoAgentEventRepository(AgentEventRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_events")

    def append(self, event: AgentEvent) -> AgentEvent:
        for _ in range(MAX_APPEND_ATTEMPTS):
            latest = self.list_latest(event.session_id, limit=1)
            candidate = replace(event, seq=(latest[0].seq + 1) if latest else 1)
            try:
                self._table.put_item(
                    Item=event_to_item(candidate),
                    ConditionExpression="attribute_not_exists(seq)",
                )
                return candidate
            except ClientError as error:
                if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                    raise
        raise AgentEventConflictError("could not reserve the next event sequence")

    def list_for_session(
        self, session_id: str, *, after_seq: int = 0, limit: int = 100
    ) -> list[AgentEvent]:
        response = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id)
            & Key("seq").gt(after_seq),
            Limit=limit,
        )
        return [event_from_item(item) for item in response.get("Items", [])]

    def list_latest(self, session_id: str, limit: int = 20) -> list[AgentEvent]:
        response = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [event_from_item(item) for item in response.get("Items", [])]


def finding_to_item(finding: AgentFinding) -> dict[str, Any]:
    item: dict[str, Any] = {
        "session_id": finding.session_id,
        "finding_id": finding.finding_id,
        "kind": finding.kind.value,
        "dimension": finding.dimension,
        "dimension_value": finding.dimension_value,
        "sample_count": finding.sample_count,
        "metrics": finding.metrics,
        "source": finding.source,
        "created_at": finding.created_at.isoformat(),
        "period_start": finding.period_start,
        "period_end": finding.period_end,
        "opaque_refs": finding.opaque_refs,
        "expires_at": finding.expires_at,
    }
    return to_dynamodb({key: value for key, value in item.items() if value is not None})


def finding_from_item(item: dict[str, Any]) -> AgentFinding:
    data = from_dynamodb(item)
    return AgentFinding(
        session_id=data["session_id"],
        finding_id=data["finding_id"],
        kind=AgentFindingKind(data["kind"]),
        dimension=data["dimension"],
        dimension_value=data["dimension_value"],
        sample_count=int(data["sample_count"]),
        metrics={key: float(value) for key, value in data.get("metrics", {}).items()},
        source=data["source"],
        created_at=datetime.fromisoformat(data["created_at"]),
        period_start=data.get("period_start"),
        period_end=data.get("period_end"),
        opaque_refs=dict(data.get("opaque_refs", {})),
        expires_at=data.get("expires_at"),
    )


class DynamoAgentFindingRepository(AgentFindingRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("agent_findings")

    def create_once(self, finding: AgentFinding) -> AgentFinding:
        try:
            self._table.put_item(
                Item=finding_to_item(finding),
                ConditionExpression="attribute_not_exists(finding_id)",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get(finding.session_id, finding.finding_id)
            if existing is not None:
                return existing
        return finding

    def get(self, session_id: str, finding_id: str) -> AgentFinding | None:
        item = self._table.get_item(
            Key={"session_id": session_id, "finding_id": finding_id}
        ).get("Item")
        return finding_from_item(item) if item else None

    def list_for_session(self, session_id: str, limit: int = 100) -> list[AgentFinding]:
        response = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id), Limit=limit
        )
        return [finding_from_item(item) for item in response.get("Items", [])]


class OptimizerInsightConflictError(Exception):
    """The insight changed (or already exists) since it was read."""


def insight_to_item(insight: OptimizerInsight) -> dict[str, Any]:
    item: dict[str, Any] = {
        "insight_id": insight.insight_id,
        "statement": insight.statement,
        "kind": insight.kind.value,
        "scope_key": insight.scope_key,
        "status": insight.status.value,
        "sample_count": insight.sample_count,
        "created_at": insight.created_at.isoformat(),
        "last_evaluated_at": insight.last_evaluated_at.isoformat(),
        "review_after": insight.review_after.isoformat(),
        "evidence_summary": insight.evidence_summary,
        "period_start": insight.period_start,
        "period_end": insight.period_end,
        "dataset_snapshot_ids": list(insight.dataset_snapshot_ids),
        "finding_ids": list(insight.finding_ids),
        "schema_version": insight.schema_version,
        "origin_session_id": insight.origin_session_id,
        "origin_run_id": insight.origin_run_id,
        "supersedes_id": insight.supersedes_id,
        "rev": insight.rev,
    }
    return to_dynamodb({key: value for key, value in item.items() if value is not None})


def insight_from_item(item: dict[str, Any]) -> OptimizerInsight:
    data = from_dynamodb(item)
    return OptimizerInsight(
        insight_id=data["insight_id"],
        statement=data["statement"],
        kind=OptimizerInsightKind(data["kind"]),
        scope_key=data["scope_key"],
        status=OptimizerInsightStatus(data["status"]),
        sample_count=int(data["sample_count"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        last_evaluated_at=datetime.fromisoformat(data["last_evaluated_at"]),
        review_after=datetime.fromisoformat(data["review_after"]),
        evidence_summary={
            key: float(value) for key, value in data.get("evidence_summary", {}).items()
        },
        period_start=data.get("period_start"),
        period_end=data.get("period_end"),
        dataset_snapshot_ids=tuple(data.get("dataset_snapshot_ids", [])),
        finding_ids=tuple(data.get("finding_ids", [])),
        schema_version=data.get("schema_version"),
        origin_session_id=data.get("origin_session_id"),
        origin_run_id=data.get("origin_run_id"),
        supersedes_id=data.get("supersedes_id"),
        rev=int(data.get("rev", 0)),
    )


class DynamoOptimizerInsightRepository(OptimizerInsightRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table("optimizer_insights")

    def create(self, insight: OptimizerInsight) -> OptimizerInsight:
        try:
            self._table.put_item(
                Item=insight_to_item(insight),
                ConditionExpression="attribute_not_exists(insight_id)",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise OptimizerInsightConflictError(insight.insight_id) from error
            raise
        return insight

    def get(self, insight_id: str) -> OptimizerInsight | None:
        item = self._table.get_item(Key={"insight_id": insight_id}).get("Item")
        return insight_from_item(item) if item else None

    def update(self, insight: OptimizerInsight, expected_rev: int) -> OptimizerInsight:
        updated = replace(insight, rev=expected_rev + 1)
        try:
            self._table.put_item(
                Item=insight_to_item(updated),
                ConditionExpression="rev = :expected",
                ExpressionAttributeValues={":expected": expected_rev},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise OptimizerInsightConflictError(insight.insight_id) from error
            raise
        return updated

    def list_by_scope(
        self, scope_key: str, status: OptimizerInsightStatus, limit: int = 50
    ) -> list[OptimizerInsight]:
        response = self._table.query(
            IndexName="ScopeStatusIdx",
            KeyConditionExpression=Key("scope_key").eq(scope_key)
            & Key("status").eq(status.value),
            Limit=limit,
        )
        return [insight_from_item(item) for item in response.get("Items", [])]

    def list_due_for_review(
        self, before: datetime, limit: int = 50
    ) -> list[OptimizerInsight]:
        response = self._table.query(
            IndexName="StatusReviewIdx",
            KeyConditionExpression=Key("status").eq(
                OptimizerInsightStatus.SUPPORTED.value
            )
            & Key("review_after").lte(before.isoformat()),
            Limit=limit,
        )
        return [insight_from_item(item) for item in response.get("Items", [])]
