from __future__ import annotations

from types import SimpleNamespace

from src.application.ports.audit_port import AuditEntry
from src.infrastructure.monitoring.audit_collector import (
    _after_call,
    _before_call,
    _resources_for_operation,
)
from src.infrastructure.monitoring.audit_context import (
    AuditContext,
    reset_audit_context,
    set_audit_context,
)
from src.infrastructure.monitoring.audit_transport import (
    audit_context_from_headers,
    audit_context_headers,
)


class RecordingAuditPort:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def test_transact_write_collection_skips_reads_and_keeps_only_keys() -> None:
    resources = _resources_for_operation(
        "TransactWriteItems",
        {
            "TransactItems": [
                {
                    "Put": {
                        "TableName": "alerts",
                        "Item": {
                            "alert_id": {"S": "alert-1"},
                            "customer_name": {"S": "private"},
                        },
                    }
                },
                {
                    "ConditionCheck": {
                        "TableName": "alerts",
                        "Key": {"alert_id": {"S": "alert-2"}},
                    }
                },
                {
                    "Delete": {
                        "TableName": "alerts",
                        "Key": {"alert_id": {"S": "alert-3"}},
                    }
                },
            ]
        },
    )

    assert resources == [
        ("dynamodb", "alerts", "alert_id=alert-1", "Put"),
        ("dynamodb", "alerts", "alert_id=alert-3", "Delete"),
    ]


def test_successful_write_is_committed_with_user_and_worker_context(
    monkeypatch,
) -> None:
    from src.infrastructure.persistence.database.dynamodb import audit_factory

    audit = RecordingAuditPort()
    monkeypatch.setattr(audit_factory, "get_audit_repository", lambda: audit)
    token = set_audit_context(
        AuditContext(
            actor_type="user",
            actor_id="user-7",
            worker_name="workflows.alert_review.run",
            correlation_id="corr-1",
            parent_id="task-1",
        )
    )
    context: dict = {}
    try:
        _before_call(
            SimpleNamespace(name="PutItem"),
            {
                "TableName": "workflow_executions",
                "Item": {
                    "workflow_id": {"S": "workflow-4"},
                    "payload": {"S": "secret"},
                },
            },
            context,
        )
        _after_call({"ResponseMetadata": {}}, context)
    finally:
        reset_audit_context(token)

    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.actor_id == "user-7"
    assert entry.worker_name == "workflows.alert_review.run"
    assert entry.entity_type == "workflow_executions"
    assert entry.entity_id == "workflow_id=workflow-4"
    assert entry.correlation_id == "corr-1"
    assert entry.parent_id == "task-1"
    assert "secret" not in repr(entry)


def test_signed_context_transport_rejects_tampering() -> None:
    token = set_audit_context(
        AuditContext(
            actor_type="user",
            actor_id="user-11",
            worker_name="simulator.tick",
            correlation_id="corr-11",
            parent_id="task-11",
        )
    )
    try:
        headers = audit_context_headers()
    finally:
        reset_audit_context(token)

    propagated = audit_context_from_headers(headers)
    assert propagated is not None
    assert propagated.actor_id == "user-11"
    assert propagated.worker_name == "simulator.tick"

    tampered = {**headers, "X-ARIA-Audit-Context": headers["X-ARIA-Audit-Context"][:-1]}
    assert audit_context_from_headers(tampered) is None
