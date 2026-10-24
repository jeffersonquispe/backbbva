from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from src.application.ports.agent_insight_port import (
    AgentInsight,
    AgentInsightKind,
    AgentInsightStatus,
)
from src.application.ports.agent_link_port import AgentLink
from src.application.ports.agent_message_port import AgentMessage
from src.application.ports.agent_session_summary_port import AgentSessionSummary
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

MESSAGES_TABLE = "agent_messages"
INSIGHTS_TABLE = "agent_insights"
LINKS_TABLE = "agent_links"
SUMMARIES_TABLE = "agent_session_summaries"


class DynamoAgentMessageRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(MESSAGES_TABLE)

    def create_once(self, message: AgentMessage) -> AgentMessage:
        item = _encode(asdict(message))
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(session_id)",
            )
            return message
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get_by_client_message_id(
                message.session_id, message.client_message_id
            )
            if existing is None:
                raise
            return existing

    def get_by_client_message_id(
        self, session_id: str, client_message_id: str
    ) -> AgentMessage | None:
        item = self._table.get_item(
            Key={"session_id": session_id, "client_message_id": client_message_id},
            ConsistentRead=True,
        ).get("Item")
        return _message(item) if item else None

    def list_after_seq(
        self, session_id: str, after_seq: int, limit: int = 50
    ) -> list[AgentMessage]:
        result = self._table.query(
            IndexName="SessionSeqIdx",
            KeyConditionExpression=Key("session_id").eq(session_id)
            & Key("seq").gt(after_seq),
            ScanIndexForward=True,
            Limit=max(1, min(limit, 50)),
        )
        return [_message(item) for item in result.get("Items", [])]

    def count_for_session(self, session_id: str) -> int:
        total = 0
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("session_id").eq(session_id),
            "Select": "COUNT",
        }
        while True:
            page = self._table.query(**kwargs)
            total += int(page.get("Count", 0))
            if "LastEvaluatedKey" not in page:
                return total
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


class DynamoAgentInsightRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(INSIGHTS_TABLE)

    def create(self, insight: AgentInsight) -> AgentInsight:
        item = _encode(asdict(insight))
        item["scope_key"] = _scope_key(insight.scope)
        item["status"] = insight.status.value
        item["kind"] = insight.kind.value
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(session_id)",
            )
            return insight
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get(insight.session_id, insight.insight_id)
            if existing is None:
                raise
            return existing

    def get(self, session_id: str, insight_id: str) -> AgentInsight | None:
        item = self._table.get_item(
            Key={"session_id": session_id, "insight_id": insight_id}
        ).get("Item")
        return _insight(item) if item else None

    def update(self, insight: AgentInsight, expected_rev: int) -> AgentInsight:
        item = _encode(asdict(insight))
        item["scope_key"] = _scope_key(insight.scope)
        item["status"] = insight.status.value
        item["kind"] = insight.kind.value
        item["rev"] = expected_rev + 1
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="rev = :expected",
                ExpressionAttributeValues={":expected": expected_rev},
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise AgentInsightRevisionConflict(
                    "insight revision changed"
                ) from error
            raise
        return _insight(item)

    def list_for_session(
        self,
        session_id: str,
        status: AgentInsightStatus | None = None,
        limit: int = 100,
    ) -> list[AgentInsight]:
        safe_limit = max(1, min(limit, 100))
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("session_id").eq(session_id),
            "ScanIndexForward": False,
            "Limit": safe_limit,
        }
        if status is not None:
            kwargs["FilterExpression"] = Attr("status").eq(status.value)
        rows: list[AgentInsight] = []
        while len(rows) < safe_limit:
            result = self._table.query(**kwargs)
            rows.extend(_insight(item) for item in result.get("Items", []))
            if "LastEvaluatedKey" not in result:
                break
            kwargs["ExclusiveStartKey"] = result["LastEvaluatedKey"]
        return rows[:safe_limit]

    def list_active_by_scope(
        self, scope_key: str, limit: int = 100
    ) -> list[AgentInsight]:
        result = self._table.query(
            IndexName="ScopeStatusIdx",
            KeyConditionExpression=Key("scope_key").eq(scope_key)
            & Key("status").eq(AgentInsightStatus.ACTIVE.value),
            Limit=max(1, min(limit, 100)),
        )
        return [_insight(item) for item in result.get("Items", [])]


class AgentInsightRevisionConflict(Exception):
    pass


class DynamoAgentLinkRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(LINKS_TABLE)

    def create_once(self, link: AgentLink) -> AgentLink:
        item = _encode(asdict(link))
        item["link_key"] = _link_key(link)
        item["src_key"] = f"{link.source_type}#{link.source_id}"
        item["dst_key"] = f"{link.target_type}#{link.target_id}"
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(session_id)",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
        return link

    def list_from(
        self, session_id: str, source_type: str, source_id: str
    ) -> list[AgentLink]:
        prefix = f"{source_type}#{source_id}#"
        result = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id)
            & Key("link_key").begins_with(prefix)
        )
        return [_link(item) for item in result.get("Items", [])]

    def list_to(self, target_type: str, target_id: str) -> list[AgentLink]:
        result = self._table.query(
            IndexName="DstIdx",
            KeyConditionExpression=Key("dst_key").eq(f"{target_type}#{target_id}"),
        )
        return [_link(item) for item in result.get("Items", [])]


class DynamoAgentSessionSummaryRepository:
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(SUMMARIES_TABLE)

    def create(self, summary: AgentSessionSummary) -> AgentSessionSummary:
        try:
            self._table.put_item(
                Item=_encode(asdict(summary)),
                ConditionExpression="attribute_not_exists(session_id)",
            )
            return summary
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = self.get(summary.session_id, summary.version)
            if existing is None:
                raise
            return existing

    def get_latest(self, session_id: str) -> AgentSessionSummary | None:
        result = self._table.query(
            KeyConditionExpression=Key("session_id").eq(session_id),
            ScanIndexForward=False,
            Limit=1,
        )
        items = result.get("Items", [])
        return _summary(items[0]) if items else None

    def get(self, session_id: str, version: int) -> AgentSessionSummary | None:
        item = self._table.get_item(
            Key={"session_id": session_id, "version": version}
        ).get("Item")
        return _summary(item) if item else None


def _encode(value: Any) -> Any:
    if isinstance(value, dict):
        encoded = {}
        for key, item in value.items():
            if item is None:
                continue
            if key == "expires_at" and isinstance(item, datetime):
                encoded[key] = int(item.timestamp())
            else:
                encoded[key] = _encode(item)
        return encoded
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def _message(item: dict[str, Any]) -> AgentMessage:
    return AgentMessage(
        session_id=item["session_id"],
        client_message_id=item["client_message_id"],
        message_id=item["message_id"],
        seq=int(item["seq"]),
        role=item["role"],
        content=item["content"],
        author_id=item["author_id"],
        created_at=datetime.fromisoformat(item["created_at"]),
        redaction_counts={
            key: int(value) for key, value in item.get("redaction_counts", {}).items()
        },
        extracted_insight_ids=tuple(item.get("extracted_insight_ids", [])),
        run_id=item.get("run_id"),
        expires_at=_expires(item.get("expires_at")),
        references=tuple(dict(entry) for entry in item.get("references", [])),
        context_used=tuple(dict(entry) for entry in item.get("context_used", [])),
    )


def _insight(item: dict[str, Any]) -> AgentInsight:
    return AgentInsight(
        session_id=item["session_id"],
        insight_id=item["insight_id"],
        kind=AgentInsightKind(item["kind"]),
        statement=item["statement"],
        scope=item.get("scope", {}),
        status=AgentInsightStatus(item["status"]),
        proposed_by=item["proposed_by"],
        author_id=item["author_id"],
        source_message_id=item.get("source_message_id"),
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        confidence=float(item["confidence"])
        if item.get("confidence") is not None
        else None,
        confirmed_by=item.get("confirmed_by"),
        confirmed_at=datetime.fromisoformat(item["confirmed_at"])
        if item.get("confirmed_at")
        else None,
        supersedes_id=item.get("supersedes_id"),
        expires_at=_expires(item.get("expires_at")),
        rev=int(item.get("rev", 0)),
    )


def _link(item: dict[str, Any]) -> AgentLink:
    return AgentLink(
        session_id=item["session_id"],
        source_type=item["source_type"],
        source_id=item["source_id"],
        relation=item["relation"],
        target_type=item["target_type"],
        target_id=item["target_id"],
        created_at=datetime.fromisoformat(item["created_at"]),
        expires_at=(_expires(item.get("expires_at"))),
    )


def _summary(item: dict[str, Any]) -> AgentSessionSummary:
    return AgentSessionSummary(
        session_id=item["session_id"],
        version=int(item["version"]),
        content=item["content"],
        covers_seq_from=int(item["covers_seq_from"]),
        covers_seq_to=int(item["covers_seq_to"]),
        created_at=datetime.fromisoformat(item["created_at"]),
        expires_at=(_expires(item.get("expires_at"))),
    )


def _scope_key(scope: dict[str, str]) -> str:
    return f"{scope.get('type', 'all')}#{scope.get('ref', 'all')}"


def _link_key(link: AgentLink) -> str:
    return (
        f"{link.source_type}#{link.source_id}#{link.relation}#"
        f"{link.target_type}#{link.target_id}"
    )


def _expires(value: int | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.fromtimestamp(int(value), UTC)
