from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status

from src.application.dtos.dataset_dtos import (
    AppendDatasetRowsInput,
    CreateEmptyDatasetInput,
    ExtractDatasetInput,
    GetDatasetRowsInput,
    UploadDatasetInput,
)
from src.application.use_cases.datasets.analyze_dataset_on_demand import (
    AnalyzeDatasetOnDemandUseCase,
)
from src.application.use_cases.datasets.append_dataset_rows import (
    AppendDatasetRowsUseCase,
)
from src.application.use_cases.datasets.create_empty_dataset import (
    CreateEmptyDatasetUseCase,
)
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase
from src.application.use_cases.datasets.extract_dataset import ExtractDatasetUseCase
from src.application.use_cases.datasets.get_dataset_rows import GetDatasetRowsUseCase
from src.application.use_cases.datasets.get_dataset_summary import (
    GetDatasetSummaryUseCase,
)
from src.application.use_cases.datasets.get_dataset_template import (
    GetDatasetTemplateUseCase,
)
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase
from src.application.use_cases.test_runs.list_datasets import ListDatasetsUseCase
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_analyze_dataset_on_demand_use_case,
    get_append_dataset_rows_use_case,
    get_create_empty_dataset_use_case,
    get_delete_dataset_use_case,
    get_extract_dataset_use_case,
    get_get_dataset_rows_use_case,
    get_get_dataset_summary_use_case,
    get_get_dataset_template_use_case,
    get_list_datasets_use_case,
    get_upload_dataset_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    AppendDatasetRowsRequest,
    AppendDatasetRowsResponse,
    CreateEmptyDatasetRequest,
    DatasetResponse,
    DatasetRowsResponse,
    DatasetSummaryResponse,
    DeleteDatasetResponse,
    ExtractDatasetRequest,
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


@router.post(
    "/datasets/empty",
    response_model=UploadDatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_empty_dataset(
    request: CreateEmptyDatasetRequest,
    use_case: Annotated[
        CreateEmptyDatasetUseCase, Depends(get_create_empty_dataset_use_case)
    ],
):
    try:
        return use_case.execute(
            CreateEmptyDatasetInput(name=request.name, fields=request.fields)
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/datasets/extract",
    response_model=UploadDatasetResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def extract_dataset(
    request: ExtractDatasetRequest,
    use_case: Annotated[ExtractDatasetUseCase, Depends(get_extract_dataset_use_case)],
):
    try:
        return use_case.execute(
            ExtractDatasetInput(
                source_names=request.source_names,
                filters=request.filters,
                percentage=request.percentage,
                target_name=request.target_name,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/datasets/{name}/rows",
    response_model=AppendDatasetRowsResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def append_dataset_rows(
    name: str,
    request: AppendDatasetRowsRequest,
    use_case: Annotated[
        AppendDatasetRowsUseCase, Depends(get_append_dataset_rows_use_case)
    ],
):
    try:
        return use_case.execute(
            AppendDatasetRowsInput(name=name, rows=request.rows)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/datasets/{name}/rows", response_model=DatasetRowsResponse)
def get_dataset_rows(
    name: str,
    use_case: Annotated[GetDatasetRowsUseCase, Depends(get_get_dataset_rows_use_case)],
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, gt=0, le=500),
):
    try:
        return use_case.execute(
            GetDatasetRowsInput(name=name, offset=offset, limit=limit)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/datasets/{name}/template")
def get_dataset_template(
    name: str,
    use_case: Annotated[
        GetDatasetTemplateUseCase, Depends(get_get_dataset_template_use_case)
    ],
):
    try:
        output = use_case.execute(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=output.content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{output.filename}"'},
    )


@router.post(
    "/datasets/{name}/analyze",
    response_model=UploadDatasetResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def analyze_dataset_on_demand(
    name: str,
    use_case: Annotated[
        AnalyzeDatasetOnDemandUseCase, Depends(get_analyze_dataset_on_demand_use_case)
    ],
):
    return use_case.execute(name)
