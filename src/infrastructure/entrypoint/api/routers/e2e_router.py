from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.local_auth_port import LocalUser
from src.application.use_cases.e2e.clean_e2e_state import CleanE2EStateUseCase
from src.infrastructure.core.config import genai_config
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.factories.e2e_factory import (
    get_clean_e2e_state_use_case,
)
from src.infrastructure.persistence.object_storage.minio import get_object_storage

router = APIRouter(prefix="/e2e", tags=["e2e"])


@router.post("/clean")
def clean_e2e_state(
    _: Annotated[LocalUser, Depends(require_permission("alert_schema"))],
    use_case: Annotated[CleanE2EStateUseCase, Depends(get_clean_e2e_state_use_case)],
) -> dict[str, object]:
    """Delete application data for the real E2E suite.

    The destructive operation deliberately lives behind the API so the E2E
    runner never needs DynamoDB credentials or a second network path.
    """
    if (
        genai_config.GENAI_ENVIRONMENT != "local"
        or not genai_config.E2E_CLEANUP_ENABLED
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="E2E cleanup is not enabled for this API environment",
        )

    result = use_case.execute()
    return {
        "deleted_items": result.deleted_items,
        "preserved_tables": result.preserved_tables,
        "table_count": result.table_count,
    }


@router.get("/alerts/{alert_id}/raw-access-audit")
def get_raw_access_audit(
    alert_id: UUID,
    _: Annotated[LocalUser, Depends(require_permission("alert_schema"))],
) -> list[dict[str, str]]:
    """Read raw-access audit artifacts for a local E2E alert only."""
    if (
        genai_config.GENAI_ENVIRONMENT != "local"
        or not genai_config.E2E_CLEANUP_ENABLED
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    storage = get_object_storage()
    prefix = f"alerts/{alert_id}/audit/raw-access/"
    keys = [key for key in storage.list_keys(".json") if key.startswith(prefix)]
    result = []
    for key in keys:
        try:
            item = json.loads(storage.get_bytes(key))
        except (ValueError, TypeError):
            continue
        if item.get("alert_id") == str(alert_id):
            result.append(item)
    return result
