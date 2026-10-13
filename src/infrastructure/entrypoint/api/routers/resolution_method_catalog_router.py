from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.resolution_method_catalog_port import ResolutionMethod
from src.application.use_cases.resolution_method_catalog.create_resolution_method import (
    CreateResolutionMethodUseCase,
)
from src.application.use_cases.resolution_method_catalog.delete_resolution_method import (
    DeleteResolutionMethodUseCase,
)
from src.application.use_cases.resolution_method_catalog.list_resolution_methods import (
    ListResolutionMethodsUseCase,
)
from src.application.use_cases.resolution_method_catalog.update_resolution_method import (
    ResolutionMethodNotFoundError,
    UpdateResolutionMethodUseCase,
)
from src.infrastructure.entrypoint.api.factories.resolution_method_catalog_factory import (
    get_create_resolution_method_use_case,
    get_delete_resolution_method_use_case,
    get_list_resolution_methods_use_case,
    get_update_resolution_method_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateResolutionMethodRequest,
    ResolutionMethodSchema,
    UpdateResolutionMethodRequest,
)

router = APIRouter(
    prefix="/resolution-method-catalog", tags=["resolution-method-catalog"]
)


@router.get("", response_model=list[ResolutionMethodSchema])
def list_resolution_methods(
    use_case: Annotated[
        ListResolutionMethodsUseCase, Depends(get_list_resolution_methods_use_case)
    ],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post(
    "", response_model=ResolutionMethodSchema, status_code=status.HTTP_201_CREATED
)
def create_resolution_method(
    request: CreateResolutionMethodRequest,
    use_case: Annotated[
        CreateResolutionMethodUseCase, Depends(get_create_resolution_method_use_case)
    ],
):
    return _to_schema(use_case.execute(request.value, request.resolution_tag))


@router.patch("/{entry_id}", response_model=ResolutionMethodSchema)
def update_resolution_method(
    entry_id: str,
    request: UpdateResolutionMethodRequest,
    use_case: Annotated[
        UpdateResolutionMethodUseCase, Depends(get_update_resolution_method_use_case)
    ],
):
    try:
        entry = use_case.execute(
            entry_id,
            value=request.value,
            resolution_tag=request.resolution_tag,
            active=request.active,
        )
    except ResolutionMethodNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resolution_method(
    entry_id: str,
    use_case: Annotated[
        DeleteResolutionMethodUseCase, Depends(get_delete_resolution_method_use_case)
    ],
):
    use_case.execute(entry_id)


def _to_schema(entry: ResolutionMethod) -> ResolutionMethodSchema:
    return ResolutionMethodSchema(
        id=entry.id,
        value=entry.value,
        resolution_tag=entry.resolution_tag,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
