from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.application.use_cases.audit.query_audit_log import QueryAuditLog
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.audit_log_factory import (
    get_query_audit_log_use_case,
)

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", dependencies=[Depends(require_permission("monitor"))])
def query_audit_logs(
    from_date: Annotated[date, Query()],
    to_date: Annotated[date, Query()],
    use_case: Annotated[QueryAuditLog, Depends(get_query_audit_log_use_case)],
    limit: Annotated[int, Query(ge=1, le=10000)] = 1000,
) -> list[dict[str, Any]]:
    try:
        return use_case.execute(from_date=from_date, to_date=to_date, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
