from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from celery import states
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.application.dtos.model_dtos import CreateModelInput
from src.application.ports.model_port import (
    FieldTransform,
    HistoricalFeature,
    TrainingConfig,
)
from src.application.use_cases.models.activate_model import ActivateModelUseCase
from src.application.use_cases.models.create_model import CreateModelUseCase
from src.application.use_cases.models.delete_model import DeleteModelUseCase
from src.application.use_cases.models.feature_engineering import (
    FeatureCapabilitiesUseCase,
    FeatureRecipeProblem,
    FeatureTemplatesUseCase,
    PreviewFeaturesUseCase,
)
from src.application.use_cases.models.get_model import GetModelUseCase
from src.application.use_cases.models.list_models import ListModelsUseCase
from src.application.use_cases.models.start_model_training import (
    StartModelTrainingUseCase,
)
from src.domain.models.exceptions import ModelNotFoundError
from src.infrastructure.entrypoint.api.factories.model_factory import (
    get_activate_model_use_case,
    get_create_model_use_case,
    get_delete_model_use_case,
    get_feature_capabilities_use_case,
    get_feature_templates_use_case,
    get_get_model_use_case,
    get_list_models_use_case,
    get_preview_features_use_case,
    get_start_model_training_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateModelRequest,
    DeleteModelResponse,
    ModelResponse,
    StartModelTrainingResponse,
)
from src.infrastructure.queues.celery.app import app as celery_app

router = APIRouter(prefix="/models", tags=["models"])


@router.post("", response_model=ModelResponse, status_code=status.HTTP_201_CREATED)
def create_model(
    request: CreateModelRequest,
    use_case: Annotated[CreateModelUseCase, Depends(get_create_model_use_case)],
):
    return use_case.execute(
        CreateModelInput(
            tag=request.tag,
            description=request.description,
            dataset_name=request.dataset_name,
            target_field=request.target_field,
            positive_labels=request.positive_labels,
            feature_transforms=[
                FieldTransform(
                    field=t.field,
                    kind=t.kind,
                    reference_field=t.reference_field,
                    top_n=t.top_n,
                )
                for t in request.feature_transforms
            ],
            created_by=request.created_by,
            historical_features=[
                HistoricalFeature(**f.model_dump()) for f in request.historical_features
            ],
            training_config=TrainingConfig(**request.training_config.model_dump()),
            feature_configuration=request.feature_configuration,
        )
    )


@router.get("", response_model=list[ModelResponse])
def list_models(
    use_case: Annotated[ListModelsUseCase, Depends(get_list_models_use_case)],
):
    return use_case.execute()


class FeaturePreviewRequest(BaseModel):
    target_field: str | None = None
    configuration: dict[str, Any]
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class FeaturePreviewQueuedResponse(BaseModel):
    task_id: str
    status: str = "PENDING"


class FeaturePreviewStatusResponse(BaseModel):
    task_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


class FeatureTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    configuration: dict[str, Any]


@router.get("/features/operations")
def get_feature_operations(
    use_case: Annotated[
        FeatureCapabilitiesUseCase, Depends(get_feature_capabilities_use_case)
    ],
):
    return use_case.execute()


@router.post(
    "/features/preview",
    response_model=FeaturePreviewQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def preview_features(
    request: FeaturePreviewRequest,
    use_case: Annotated[PreviewFeaturesUseCase, Depends(get_preview_features_use_case)],
):
    try:
        # Reject malformed or oversized input before it reaches Redis, but leave
        # evaluation itself to the worker so a costly recipe cannot occupy an API worker.
        configuration = use_case.validate(
            request.configuration, request.rows, request.target_field
        )
        task = celery_app.send_task(
            "models.preview_features",
            args=[configuration, request.rows, request.target_field],
        )
        return FeaturePreviewQueuedResponse(task_id=task.id)
    except FeatureRecipeProblem as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/features/preview/{task_id}", response_model=FeaturePreviewStatusResponse)
def get_feature_preview(task_id: str):
    task = AsyncResult(task_id, app=celery_app)
    if task.state in {states.PENDING, states.RECEIVED, states.STARTED, states.RETRY}:
        return FeaturePreviewStatusResponse(task_id=task_id, status="PENDING")
    if task.state == states.SUCCESS:
        return FeaturePreviewStatusResponse(
            task_id=task_id, status="READY", result=task.result
        )
    return FeaturePreviewStatusResponse(
        task_id=task_id,
        status="FAILED",
        error=str(task.result) if task.result else task.state,
    )


@router.get("/feature-templates")
def list_feature_templates(
    use_case: Annotated[
        FeatureTemplatesUseCase, Depends(get_feature_templates_use_case)
    ],
):
    return use_case.list()


@router.post("/feature-templates", status_code=status.HTTP_201_CREATED)
def create_feature_template(
    request: FeatureTemplateRequest,
    use_case: Annotated[
        FeatureTemplatesUseCase, Depends(get_feature_templates_use_case)
    ],
):
    try:
        return use_case.create(request.name, request.description, request.configuration)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete(
    "/feature-templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_feature_template(
    template_id: UUID,
    use_case: Annotated[
        FeatureTemplatesUseCase, Depends(get_feature_templates_use_case)
    ],
):
    use_case.delete(str(template_id))


@router.get("/{model_id}", response_model=ModelResponse)
def get_model(
    model_id: UUID,
    use_case: Annotated[GetModelUseCase, Depends(get_get_model_use_case)],
):
    model = use_case.execute(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@router.delete("/{model_id}", response_model=DeleteModelResponse)
def delete_model(
    model_id: UUID,
    use_case: Annotated[DeleteModelUseCase, Depends(get_delete_model_use_case)],
):
    use_case.execute(model_id)
    return DeleteModelResponse(id=model_id, deleted=True)


@router.post(
    "/{model_id}/train",
    response_model=StartModelTrainingResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def train_model(
    model_id: UUID,
    use_case: Annotated[
        StartModelTrainingUseCase, Depends(get_start_model_training_use_case)
    ],
):
    try:
        return use_case.execute(model_id)
    except ModelNotFoundError:
        raise HTTPException(status_code=404, detail="Model not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{model_id}/activate", response_model=ModelResponse)
def activate_model(
    model_id: UUID,
    use_case: Annotated[ActivateModelUseCase, Depends(get_activate_model_use_case)],
):
    try:
        return use_case.execute(model_id)
    except ModelNotFoundError:
        raise HTTPException(status_code=404, detail="Model not found")
