from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from src.application.use_cases.analyst_capacity.get_analyst_capacity_import import (
    GetAnalystCapacityImportUseCase,
)
from src.application.use_cases.analyst_capacity.upload_analyst_capacity_import import (
    UploadAnalystCapacityImportUseCase,
)
from src.infrastructure.entrypoint.api.factories.analyst_capacity_factory import (
    get_get_analyst_capacity_import_use_case,
    get_upload_analyst_capacity_import_use_case,
)
from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportStatus,
)
from src.infrastructure.entrypoint.api.schemas import (
    AnalystCapacityImportProfileSchema,
    AnalystCapacityImportResponse,
    UploadAnalystCapacityImportResponse,
)

router = APIRouter(tags=["analyst-capacity"])

# A capacity workbook is a handful of profile rows + up to 31 day
# assignments - a few KB. 2MB is a generous ceiling, not a real limit.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


@router.post(
    "/analyst-capacity/imports",
    response_model=UploadAnalystCapacityImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_analyst_capacity_import(
    use_case: Annotated[
        UploadAnalystCapacityImportUseCase,
        Depends(get_upload_analyst_capacity_import_use_case),
    ],
    file: UploadFile,
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large (max 2MB)")
    task_id = use_case.execute(content)
    return UploadAnalystCapacityImportResponse(
        task_id=task_id, status=AnalystCapacityImportStatus.PENDING
    )


@router.get(
    "/analyst-capacity/imports/{task_id}",
    response_model=AnalystCapacityImportResponse,
)
def get_analyst_capacity_import(
    task_id: str,
    use_case: Annotated[
        GetAnalystCapacityImportUseCase,
        Depends(get_get_analyst_capacity_import_use_case),
    ],
):
    result = use_case.execute(task_id)
    return AnalystCapacityImportResponse(
        task_id=task_id,
        status=result.status,
        profiles=[
            AnalystCapacityImportProfileSchema(**asdict(p)) for p in result.profiles
        ],
        day_overrides=result.day_overrides,
        error=result.error,
    )
