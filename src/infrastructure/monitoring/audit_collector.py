from __future__ import annotations

from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from src.application.ports.audit_port import AuditEntry
from src.infrastructure.monitoring.audit_context import current_audit_context

_WRITE_OPERATIONS = {
    "PutItem",
    "UpdateItem",
    "DeleteItem",
    "BatchWriteItem",
    "TransactWriteItems",
    "PutObject",
    "CopyObject",
    "DeleteObject",
    "DeleteObjects",
    "CreateMultipartUpload",
    "UploadPart",
    "CompleteMultipartUpload",
    "AbortMultipartUpload",
    "CreateBucket",
}
_COLLECTING: ContextVar[bool] = ContextVar("aria_audit_collecting", default=False)


def install_audit_hooks(client: Any, service_name: str) -> None:
    """Collect successful data writes made through a boto3 client."""
    client.meta.events.register(
        f"before-call.{service_name}", _before_call, unique_id="aria-audit-before"
    )
    client.meta.events.register(
        f"after-call.{service_name}", _after_call, unique_id="aria-audit-after"
    )


def _before_call(
    model: Any, params: dict[str, Any], context: dict[str, Any], **_: Any
) -> None:
    operation = model.name
    if operation not in _WRITE_OPERATIONS:
        return
    context["aria_audit_operation"] = operation
    context["aria_audit_resources"] = _resources_for_operation(operation, params)


def _after_call(parsed: dict[str, Any], context: dict[str, Any], **_: Any) -> None:
    if _COLLECTING.get():
        return
    operation = context.pop("aria_audit_operation", None)
    resources = context.pop("aria_audit_resources", [])
    if not operation or not resources:
        return
    token = _COLLECTING.set(True)
    try:
        from src.infrastructure.persistence.database.dynamodb.audit_factory import (
            get_audit_repository,
        )

        audit_context = current_audit_context()
        for resource_type, resource_name, entity_id, action in resources:
            if resource_type == "dynamodb" and resource_name == "audit_log":
                continue
            get_audit_repository().write(
                AuditEntry(
                    actor_type=audit_context.actor_type,
                    actor_id=audit_context.actor_id,
                    worker_name=audit_context.worker_name,
                    action=f"{resource_type}.{action}",
                    entity_type=resource_name,
                    entity_id=entity_id,
                    correlation_id=audit_context.correlation_id,
                    parent_id=audit_context.parent_id,
                    occurred_at=datetime.now(UTC),
                    outcome="success",
                )
            )
    finally:
        _COLLECTING.reset(token)


def _resources_for_operation(
    operation: str, params: dict[str, Any]
) -> list[tuple[str, str, str | None, str]]:
    if operation in {"PutItem", "UpdateItem", "DeleteItem"}:
        name = params.get("TableName")
        key = params.get("Key") or params.get("Item") or {}
        entity_id = _key_identity(key)
        return [("dynamodb", name, entity_id, operation)] if name else []
    if operation == "TransactWriteItems":
        resources = []
        for action in params.get("TransactItems", []):
            for operation_name, request in action.items():
                table_name = request.get("TableName")
                if table_name and operation_name in {"Put", "Update", "Delete"}:
                    key = request.get("Key") or request.get("Item") or {}
                    resources.append(
                        (
                            "dynamodb",
                            table_name,
                            _key_identity(key),
                            operation_name,
                        )
                    )
        return resources
    if operation == "BatchWriteItem":
        resources = []
        for table_name, requests in params.get("RequestItems", {}).items():
            for request in requests:
                item = request.get("PutRequest", {}).get("Item") or request.get(
                    "DeleteRequest", {}
                ).get("Key", {})
                resources.append(
                    ("dynamodb", table_name, _key_identity(item), "BatchWriteItem")
                )
        return resources
    if operation in {
        "PutObject",
        "CopyObject",
        "DeleteObject",
        "DeleteObjects",
        "CreateMultipartUpload",
        "UploadPart",
        "CompleteMultipartUpload",
        "AbortMultipartUpload",
        "CreateBucket",
    }:
        bucket = params.get("Bucket")
        key = params.get("Key")
        if operation == "DeleteObjects":
            return [
                (
                    "object_storage",
                    "object",
                    f"{bucket}/{obj.get('Key', '')}",
                    operation,
                )
                for obj in params.get("Delete", {}).get("Objects", [])
            ]
        entity_type = "bucket" if operation == "CreateBucket" else "object"
        return (
            [
                (
                    "object_storage",
                    entity_type,
                    bucket if entity_type == "bucket" else f"{bucket}/{key or ''}",
                    operation,
                )
            ]
            if bucket
            else []
        )
    return []


def _key_identity(attributes: dict[str, Any]) -> str | None:
    """Keep key-like identifiers only; never persist complete item payloads."""
    if not isinstance(attributes, dict):
        return None
    values = []
    for name, value in sorted(attributes.items()):
        if not (
            name == "id"
            or name == "partition"
            or name == "log_id"
            or name.endswith("_id")
        ):
            continue
        if isinstance(value, dict):
            value = next(iter(value.values()), None)
        if isinstance(value, (str, int, float)):
            values.append(f"{name}={value}")
    return ",".join(values) or None


def record_audit(
    action: str,
    entity_type: str,
    entity_id: str | None,
    *,
    outcome: str = "success",
) -> None:
    """Record a non-SDK mutation, such as a task lifecycle or local file write."""
    if _COLLECTING.get():
        return
    token = _COLLECTING.set(True)
    try:
        from src.infrastructure.persistence.database.dynamodb.audit_factory import (
            get_audit_repository,
        )

        context = current_audit_context()
        get_audit_repository().write(
            AuditEntry(
                actor_type=context.actor_type,
                actor_id=context.actor_id,
                worker_name=context.worker_name,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                correlation_id=context.correlation_id,
                parent_id=context.parent_id,
                occurred_at=datetime.now(UTC),
                outcome=outcome,
            )
        )
    finally:
        _COLLECTING.reset(token)
