import base64
import json
from datetime import UTC, datetime

from src.application.ports.agent_audit_port import AgentAuditEvent
from src.infrastructure.persistence.database.dynamodb.repositories.agent_audit_repository import (
    DynamoAgentAuditRepository,
)


class _Table:
    def __init__(self):
        self.item = None

    def put_item(self, **kwargs):
        self.item = kwargs["Item"]

    def query(self, **kwargs):
        assert kwargs["KeyConditionExpression"] is not None
        assert kwargs["Limit"] == 1
        self.query_kwargs = kwargs
        if "ExclusiveStartKey" not in kwargs:
            return {
                "Items": [self.item],
                "LastEvaluatedKey": {"session_id": "s1", "event_key": "next"},
            }
        return {"Items": [self.item], "LastEvaluatedKey": None}


def test_session_audit_is_appendable_and_queryable_without_free_text(monkeypatch):
    table = _Table()
    monkeypatch.setattr(
        "src.infrastructure.persistence.database.dynamodb.repositories.agent_audit_repository.get_dynamodb_resource",
        lambda: type("Resource", (), {"Table": lambda _self, _name: table})(),
    )
    repository = DynamoAgentAuditRepository()
    event = AgentAuditEvent(
        session_id="s1",
        occurred_at=datetime(2026, 10, 20, tzinfo=UTC),
        event_id="e1",
        category="iteration",
        status="succeeded",
        duration_ms=24,
        cost_micros=50,
    )
    repository.append(event)
    rows, cursor = repository.list_for_session("s1", cursor=None, limit=1)
    assert rows == [event]
    assert cursor is not None
    assert "message" not in table.item
    assert "payload" not in table.item
    next_rows, next_cursor = repository.list_for_session(
        "s1", cursor=cursor, limit=1
    )
    assert next_rows == [event]
    assert next_cursor is None
    assert table.query_kwargs["ExclusiveStartKey"] == {
        "session_id": "s1", "event_key": "next"
    }


def test_session_audit_rejects_a_cursor_for_another_session(monkeypatch):
    table = _Table()
    monkeypatch.setattr(
        "src.infrastructure.persistence.database.dynamodb.repositories.agent_audit_repository.get_dynamodb_resource",
        lambda: type("Resource", (), {"Table": lambda _self, _name: table})(),
    )
    cursor = base64.urlsafe_b64encode(
        json.dumps({"session_id": "other", "event_key": "k"}).encode()
    ).decode()
    try:
        DynamoAgentAuditRepository().list_for_session("s1", cursor=cursor, limit=10)
    except ValueError as error:
        assert str(error) == "INVALID_AUDIT_CURSOR"
    else:
        raise AssertionError("cross-session cursor must be rejected")
