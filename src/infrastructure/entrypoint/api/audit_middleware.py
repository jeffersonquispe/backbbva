from __future__ import annotations

from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.infrastructure.monitoring.audit_context import (
    AuditContext,
    reset_audit_context,
    set_audit_context,
)
from src.infrastructure.monitoring.audit_transport import audit_context_from_headers


class AuditContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        propagated = audit_context_from_headers(dict(request.headers))
        token = set_audit_context(
            propagated
            or AuditContext(
                actor_type="anonymous",
                actor_id="anonymous",
                correlation_id=correlation_id,
            )
        )
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            reset_audit_context(token)
