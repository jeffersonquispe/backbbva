from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from src.application.ports.backup_catalog_port import BackupRecord
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.use_cases.backups.list_backups import ListBackupsUseCase
from src.application.use_cases.backups.request_backup import RequestBackupUseCase
from src.infrastructure.entrypoint.api.factories.backup_factory import (
    get_list_backups_use_case,
    get_request_backup_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user

router = APIRouter(prefix="/backups", tags=["backups"])
ALLOWED_ROLES = {LocalRole.RELEASE_MANAGER, LocalRole.MANAGER}


class BackupResponse(BaseModel):
    backup_id: str
    directory: str
    requested_by: str
    created_at: datetime
    updated_at: datetime
    status: str
    error: str | None = None
    dynamodb_items: int | None = None
    opensearch_documents: int | None = None
    object_storage_objects: int | None = None


def _authorize(user: LocalUser) -> None:
    if user.role not in ALLOWED_ROLES:
        raise HTTPException(status_code=403, detail="Role is not permitted to manage backups")


def _response(record: BackupRecord) -> BackupResponse:
    return BackupResponse(**{**asdict(record), "status": record.status.value})


@router.post("", response_model=BackupResponse, status_code=status.HTTP_202_ACCEPTED)
def request_backup(
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[RequestBackupUseCase, Depends(get_request_backup_use_case)],
) -> BackupResponse:
    _authorize(user)
    try:
        return _response(use_case.execute(user.email))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Backup task could not be queued") from exc


@router.get("", response_model=list[BackupResponse])
def list_backups(
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[ListBackupsUseCase, Depends(get_list_backups_use_case)],
) -> list[BackupResponse]:
    _authorize(user)
    return [_response(record) for record in use_case.execute()]
