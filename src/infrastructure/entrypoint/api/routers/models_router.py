from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.dtos.model_dtos import CreateModelInput
from src.application.ports.model_port import FieldTransform
from src.application.use_cases.models.activate_model import ActivateModelUseCase
from src.application.use_cases.models.create_model import CreateModelUseCase
from src.application.use_cases.models.delete_model import DeleteModelUseCase
from src.application.use_cases.models.get_model import GetModelUseCase
from src.application.use_cases.models.list_models import ListModelsUseCase
from src.application.use_cases.models.start_model_training import (
    ModelAlreadyTrainingError,
    StartModelTrainingUseCase,
)
from src.domain.models.exceptions import ModelNotFoundError
from src.infrastructure.entrypoint.api.factories.model_factory import (
    get_activate_model_use_case,
    get_create_model_use_case,
    get_delete_model_use_case,
    get_get_model_use_case,
    get_list_models_use_case,
    get_start_model_training_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateModelRequest,
    DeleteModelResponse,
    ModelResponse,
    StartModelTrainingResponse,
)

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
        )
    )


@router.get("", response_model=list[ModelResponse])
def list_models(
    use_case: Annotated[ListModelsUseCase, Depends(get_list_models_use_case)],
):
    return use_case.execute()


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
    except ModelAlreadyTrainingError:
        raise HTTPException(status_code=409, detail="Model is already training")


@router.post("/{model_id}/activate", response_model=ModelResponse)
def activate_model(
    model_id: UUID,
    use_case: Annotated[ActivateModelUseCase, Depends(get_activate_model_use_case)],
):
    try:
        return use_case.execute(model_id)
    except ModelNotFoundError:
        raise HTTPException(status_code=404, detail="Model not found")
