from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status

from src.application.dtos.dataset_dtos import (
    AppendDatasetRowsInput,
    CreateEmptyDatasetInput,
    ExtractDatasetInput,
    FraudMarkingAnalysisInput,
    GetDatasetRowsInput,
    UploadDatasetInput,
)
from src.application.dtos.alert_field_mapping_dtos import SaveAlertFieldMappingInput
from src.application.use_cases.datasets.analyze_dataset_on_demand import (
    AnalyzeDatasetOnDemandUseCase,
)
from src.application.use_cases.datasets.analyze_fraud_marking import (
    AnalyzeFraudMarkingUseCase,
)
from src.application.use_cases.datasets.append_dataset_rows import (
    AppendDatasetRowsUseCase,
)
from src.application.use_cases.datasets.create_empty_dataset import (
    CreateEmptyDatasetUseCase,
)
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase
from src.application.use_cases.datasets.extract_dataset import ExtractDatasetUseCase
from src.application.use_cases.datasets.get_alert_field_mapping import (
    GetAlertFieldMappingUseCase,
)
from src.application.use_cases.datasets.delete_alert_field_mapping import (
    DeleteAlertFieldMappingUseCase,
)
from src.application.use_cases.datasets.get_dataset_rows import GetDatasetRowsUseCase
from src.application.use_cases.datasets.get_dataset_summary import (
    GetDatasetSummaryUseCase,
)
from src.application.use_cases.datasets.get_dataset_template import (
    GetDatasetTemplateUseCase,
)
from src.application.use_cases.datasets.save_alert_field_mapping import (
    SaveAlertFieldMappingUseCase,
)
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase
from src.application.use_cases.test_runs.list_datasets import ListDatasetsUseCase
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_analyze_dataset_on_demand_use_case,
    get_analyze_fraud_marking_use_case,
    get_append_dataset_rows_use_case,
    get_create_empty_dataset_use_case,
    get_delete_dataset_use_case,
    get_extract_dataset_use_case,
    get_get_alert_field_mapping_use_case,
    get_delete_alert_field_mapping_use_case,
    get_get_dataset_rows_use_case,
    get_get_dataset_summary_use_case,
    get_get_dataset_template_use_case,
    get_list_datasets_use_case,
    get_save_alert_field_mapping_use_case,
    get_upload_dataset_use_case,
)
from src.infrastructure.entrypoint.api.authorization import require_permission
from src.infrastructure.entrypoint.api.schemas import (
    AlertFieldMappingResponse,
    AppendDatasetRowsRequest,
    AppendDatasetRowsResponse,
    CreateEmptyDatasetRequest,
    DatasetResponse,
    DatasetRowsResponse,
    FraudMarkingAnalysisQueuedResponse,
    DatasetSummaryResponse,
    DeleteDatasetResponse,
    ExtractDatasetRequest,
    SaveAlertFieldMappingRequest,
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
    # Starlette stores multipart uploads above its small spool threshold on
    # disk. Pass that file through to storage instead of reading the entire
    # dataset into the API process's memory.
    await file.seek(0)
    try:
        return use_case.execute(UploadDatasetInput(name=name, file=file.file))
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/datasets/{name}/summary",
    response_model=DatasetSummaryResponse | FraudMarkingAnalysisQueuedResponse,
)
def get_dataset_summary(
    name: str,
    use_case: Annotated[
        GetDatasetSummaryUseCase, Depends(get_get_dataset_summary_use_case)
    ],
    fraud_marking_use_case: Annotated[
        AnalyzeFraudMarkingUseCase, Depends(get_analyze_fraud_marking_use_case)
    ],
    response: Response,
    first_mark_field: str | None = Query(
        default=None,
        description="Dataset field holding the initial fraud mark, e.g. razon_marcacion",
    ),
    second_mark_field: str | None = Query(
        default=None,
        description="Dataset field holding the final/confirmed fraud mark, e.g. marcacion_final",
    ),
    first_mark_time_field: str | None = Query(
        default=None,
        description="Dataset field holding the timestamp of the first mark, e.g. fecha_primer_marcacion",
    ),
    second_mark_time_field: str | None = Query(
        default=None,
        description="Dataset field holding the timestamp of the second mark, e.g. fecha_ultima_marcacion",
    ),
    positive_values: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable - every value in either mark field that means "
            "'flagged as fraud', e.g. positive_values=risk&"
            "positive_values=risk-suspected. A row moving between two of "
            "these isn't counted as a false positive/negative."
        ),
    ),
):
    summary = use_case.execute(name)
    if summary is None:
        raise HTTPException(status_code=404, detail="Dataset not found")

    mark_fields = (
        first_mark_field,
        second_mark_field,
        first_mark_time_field,
        second_mark_time_field,
    )
    if any(mark_fields) or positive_values:
        if not all(mark_fields) or not positive_values:
            raise HTTPException(
                status_code=400,
                detail=(
                    "first_mark_field, second_mark_field, first_mark_time_field, "
                    "second_mark_time_field and at least one positive_values "
                    "must all be provided together"
                ),
            )
        config = {
            "first_mark_field": first_mark_field,
            "second_mark_field": second_mark_field,
            "first_mark_time_field": first_mark_time_field,
            "second_mark_time_field": second_mark_time_field,
            "positive_values": positive_values,
        }
        if summary.fraud_marking_analysis_config != config:
            analysis_input = FraudMarkingAnalysisInput(
                dataset_name=name,
                first_mark_field=first_mark_field,
                second_mark_field=second_mark_field,
                first_mark_time_field=first_mark_time_field,
                second_mark_time_field=second_mark_time_field,
                positive_values=positive_values,
            )
            operation_id = fraud_marking_use_case.schedule(analysis_input)
            if operation_id is None:
                raise HTTPException(
                    status_code=503,
                    detail="Fraud-marking analysis scheduling is unavailable",
                )
            from src.infrastructure.entrypoint.worker.celery.tasks import (
                analyze_fraud_marking_task,
            )

            analyze_fraud_marking_task.delay(
                name,
                first_mark_field,
                second_mark_field,
                first_mark_time_field,
                second_mark_time_field,
                positive_values,
                str(operation_id),
            )
            response.status_code = status.HTTP_202_ACCEPTED
            return FraudMarkingAnalysisQueuedResponse(
                dataset_name=name,
                async_operation_id=operation_id,
            )

    return summary


@router.delete(
    "/datasets/{name}",
    response_model=DeleteDatasetResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def delete_dataset(
    name: str,
    use_case: Annotated[DeleteDatasetUseCase, Depends(get_delete_dataset_use_case)],
):
    operation_id = use_case.schedule(name)
    if operation_id is None:
        use_case.execute(name)
        return DeleteDatasetResponse(name=name, deleted=True)

    # Never make a browser request wait for object-storage and DynamoDB
    # cleanup.  This is especially important for datasets created before
    # sample retention was bounded.
    # Send by registered task name so the API does not import the complete
    # worker task module (and its optional research dependencies) just to
    # enqueue a dataset deletion.
    from src.infrastructure.entrypoint.worker.celery.celery_app import app as celery_app

    celery_app.send_task("datasets.delete", args=[name, str(operation_id)])
    return DeleteDatasetResponse(
        name=name, deleted=False, async_operation_id=operation_id
    )


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
    try:
        return use_case.execute(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/datasets/{name}/alert-field-mapping",
    response_model=AlertFieldMappingResponse,
)
def get_alert_field_mapping(
    name: str,
    use_case: Annotated[
        GetAlertFieldMappingUseCase, Depends(get_get_alert_field_mapping_use_case)
    ],
):
    return use_case.execute(name)


@router.put(
    "/datasets/{name}/alert-field-mapping",
    response_model=AlertFieldMappingResponse,
    dependencies=[Depends(require_permission("alert_schema"))],
)
def save_alert_field_mapping(
    name: str,
    request: SaveAlertFieldMappingRequest,
    use_case: Annotated[
        SaveAlertFieldMappingUseCase, Depends(get_save_alert_field_mapping_use_case)
    ],
):
    return use_case.execute(
        SaveAlertFieldMappingInput(
            dataset_name=name,
            schema_version=request.schema_version,
            mappings=request.mappings,
        )
    )


@router.delete(
    "/datasets/{name}/alert-field-mapping",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("alert_schema"))],
)
def delete_alert_field_mapping(
    name: str,
    use_case: Annotated[
        DeleteAlertFieldMappingUseCase,
        Depends(get_delete_alert_field_mapping_use_case),
    ],
):
    use_case.execute(name)
