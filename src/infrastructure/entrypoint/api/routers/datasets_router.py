from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from src.application.dtos.dataset_dtos import UploadDatasetInput
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase
from src.application.use_cases.datasets.get_dataset_summary import (
    GetDatasetSummaryUseCase,
)
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase
from src.application.use_cases.test_runs.list_datasets import ListDatasetsUseCase
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_delete_dataset_use_case,
    get_get_dataset_summary_use_case,
    get_list_datasets_use_case,
    get_upload_dataset_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    DatasetResponse,
    DatasetSummaryResponse,
    DeleteDatasetResponse,
    UploadDatasetResponse,
)

router = APIRouter(tags=["datasets"])


@router.get("/datasets", response_model=list[DatasetResponse])
def list_datasets(
    use_case: Annotated[ListDatasetsUseCase, Depends(get_list_datasets_use_case)],
):
    return use_case.execute()


@router.post(
    "/datasets",
    response_model=UploadDatasetResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_dataset(
    use_case: Annotated[UploadDatasetUseCase, Depends(get_upload_dataset_use_case)],
    file: UploadFile,
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are supported")
    name = file.filename[: -len(".csv")]
    content = await file.read()
    return use_case.execute(UploadDatasetInput(name=name, content=content))


@router.get("/datasets/{name}/summary", response_model=DatasetSummaryResponse)
def get_dataset_summary(
    name: str,
    use_case: Annotated[
        GetDatasetSummaryUseCase, Depends(get_get_dataset_summary_use_case)
    ],
):
    summary = use_case.execute(name)
    if summary is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return summary


@router.delete("/datasets/{name}", response_model=DeleteDatasetResponse)
def delete_dataset(
    name: str,
    use_case: Annotated[DeleteDatasetUseCase, Depends(get_delete_dataset_use_case)],
):
    use_case.execute(name)
    return DeleteDatasetResponse(name=name, deleted=True)
