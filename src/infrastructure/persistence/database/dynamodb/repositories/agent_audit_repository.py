from __future__ import annotations

from datetime import datetime
from typing import Any

from boto3.dynamodb.conditions import Key

from src.application.ports.agent_audit_port import AgentAuditEvent, AgentAuditRepository
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)

TABLE_NAME = "agent_audit_events"


class DynamoAgentAuditRepository(AgentAuditRepository):
    def __init__(self) -> None:
        self._table = get_dynamodb_resource().Table(TABLE_NAME)

    def append(self, event: AgentAuditEvent) -> None:
        self._table.put_item(
            Item={
                "session_id": event.session_id,
                "event_key": f"{event.occurred_at.isoformat()}#{event.event_id}",
                "occurred_at": event.occurred_at.isoformat(),
                "event_id": event.event_id,
                "category": event.category,
                "status": event.status,
                "reason_code": event.reason_code,
                "duration_ms": event.duration_ms,
                "cost_micros": event.cost_micros,
                "specialist": event.specialist,
                "tool": event.tool,
                "actor": event.actor,
                "actor_id": event.actor_id,
                "entity_id": event.entity_id,
                "version": event.version,
                "snapshot_id": event.snapshot_id,
                "content_sha256": event.content_sha256,
                "policy_version": event.policy_version,
                "reason": event.reason,
            },
            ConditionExpression="attribute_not_exists(session_id) AND attribute_not_exists(event_key)",
        )

    def list_for_session(
        self, session_id: str, *, cursor: str | None, limit: int
    ) -> tuple[list[AgentAuditEvent], str | None]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("session_id").eq(session_id),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if cursor:
            import base64
            import binascii
            import json

            try:
                key = json.loads(
                    base64.b64decode(cursor, altchars=b"-_", validate=True)
                )
            except (binascii.Error, json.JSONDecodeError, ValueError) as error:
                raise ValueError("INVALID_AUDIT_CURSOR") from error
            if (
                not isinstance(key, dict)
                or key.get("session_id") != session_id
                or not isinstance(key.get("event_key"), str)
            ):
                raise ValueError("INVALID_AUDIT_CURSOR")
            kwargs["ExclusiveStartKey"] = key
        response = self._table.query(**kwargs)
        events = [
            AgentAuditEvent(
                session_id=item["session_id"],
                occurred_at=datetime.fromisoformat(item["occurred_at"]),
                event_id=item["event_id"],
                category=item["category"],
                status=item["status"],
                reason_code=item.get("reason_code"),
                duration_ms=item.get("duration_ms"),
                cost_micros=item.get("cost_micros"),
                specialist=item.get("specialist"),
                tool=item.get("tool"),
                actor=item.get("actor"),
                actor_id=item.get("actor_id"),
                entity_id=item.get("entity_id"),
                version=item.get("version"),
                snapshot_id=item.get("snapshot_id"),
                content_sha256=item.get("content_sha256"),
                policy_version=item.get("policy_version"),
                reason=item.get("reason"),
            )
            for item in response.get("Items", [])
        ]
        key = response.get("LastEvaluatedKey")
        if not key:
            return events, None
        import base64
        import json

        next_cursor = base64.urlsafe_b64encode(
            json.dumps(key, separators=(",", ":")).encode()
        ).decode()
        return events, next_cursor
