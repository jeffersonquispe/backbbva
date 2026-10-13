from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from uuid import uuid4


@dataclass
class AuditContext:
    actor_type: str = "system"
    actor_id: str = "unknown"
    worker_name: str | None = None
    correlation_id: str = ""
    parent_id: str | None = None


_context: ContextVar[AuditContext] = ContextVar(
    "aria_audit_context", default=AuditContext()
)


def current_audit_context() -> AuditContext:
    context = _context.get()
    if context.correlation_id:
        return context
    context = replace(context, correlation_id=str(uuid4()))
    _context.set(context)
    return context


def set_audit_context(context: AuditContext) -> Token[AuditContext]:
    return _context.set(context)


def update_audit_context(**changes: str | None) -> None:
    context = current_audit_context()
    for key, value in changes.items():
        setattr(context, key, value)


def reset_audit_context(token: Token[AuditContext]) -> None:
    _context.reset(token)
