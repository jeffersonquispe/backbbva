from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from celery.signals import before_task_publish, task_postrun, task_prerun

from src.infrastructure.monitoring.audit_collector import record_audit
from src.infrastructure.monitoring.audit_context import (
    AuditContext,
    current_audit_context,
    reset_audit_context,
    set_audit_context,
)

_task_token: ContextVar[Token[AuditContext] | None] = ContextVar(
    "aria_celery_audit_token", default=None
)


def register_audit_signals() -> None:
    before_task_publish.connect(
        _propagate_audit_context, weak=False, dispatch_uid="aria-audit-publish"
    )
    task_prerun.connect(
        _start_task_audit_context, weak=False, dispatch_uid="aria-audit-prerun"
    )
    task_postrun.connect(
        _end_task_audit_context, weak=False, dispatch_uid="aria-audit-postrun"
    )


def _propagate_audit_context(headers: dict[str, Any] | None = None, **_: Any) -> None:
    if headers is None:
        return
    context = current_audit_context()
    headers["aria_audit"] = {
        "actor_type": context.actor_type,
        "actor_id": context.actor_id,
        "correlation_id": context.correlation_id,
        "parent_id": headers.get("id") or context.parent_id,
    }


def _start_task_audit_context(task: Any = None, task_id: str = "", **_: Any) -> None:
    request = getattr(task, "request", None)
    headers = getattr(request, "headers", None) or {}
    propagated = headers.get("aria_audit", {})
    token = set_audit_context(
        AuditContext(
            actor_type=propagated.get("actor_type", "system"),
            actor_id=propagated.get("actor_id", "system"),
            worker_name=getattr(task, "name", None),
            correlation_id=propagated.get("correlation_id", ""),
            parent_id=propagated.get("parent_id") or getattr(request, "id", None),
        )
    )
    _task_token.set(token)
    record_audit("celery.start", "task", task_id or None)


def _end_task_audit_context(
    task: Any = None, task_id: str = "", state: str = "unknown", **_: Any
) -> None:
    token = _task_token.get()
    if token is not None:
        record_audit(
            f"celery.{state.lower()}",
            "task",
            task_id or getattr(getattr(task, "request", None), "id", None),
            outcome=state.lower(),
        )
        reset_audit_context(token)
        _task_token.set(None)
