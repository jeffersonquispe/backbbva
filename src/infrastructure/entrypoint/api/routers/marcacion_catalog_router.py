from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.marcacion_catalog_port import MarcacionCategory
from src.application.use_cases.marcacion_catalog.create_marcacion_category import (
    CreateMarcacionCategoryUseCase,
)
from src.application.use_cases.marcacion_catalog.delete_marcacion_category import (
    DeleteMarcacionCategoryUseCase,
)
from src.application.use_cases.marcacion_catalog.list_marcacion_categories import (
    ListMarcacionCategoriesUseCase,
)
from src.application.use_cases.marcacion_catalog.update_marcacion_category import (
    MarcacionCategoryNotFoundError,
    UpdateMarcacionCategoryUseCase,
)
from src.infrastructure.entrypoint.api.factories.marcacion_catalog_factory import (
    get_create_marcacion_category_use_case,
    get_delete_marcacion_category_use_case,
    get_list_marcacion_categories_use_case,
    get_update_marcacion_category_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateMarcacionCategoryRequest,
    MarcacionCategorySchema,
    UpdateMarcacionCategoryRequest,
)

router = APIRouter(prefix="/marcacion-catalog", tags=["marcacion-catalog"])


@router.get("", response_model=list[MarcacionCategorySchema])
def list_marcacion_categories(
    use_case: Annotated[
        ListMarcacionCategoriesUseCase, Depends(get_list_marcacion_categories_use_case)
    ],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post(
    "", response_model=MarcacionCategorySchema, status_code=status.HTTP_201_CREATED
)
def create_marcacion_category(
    request: CreateMarcacionCategoryRequest,
    use_case: Annotated[
        CreateMarcacionCategoryUseCase, Depends(get_create_marcacion_category_use_case)
    ],
):
    return _to_schema(use_case.execute(request.value, request.risk_label))


@router.patch("/{entry_id}", response_model=MarcacionCategorySchema)
def update_marcacion_category(
    entry_id: str,
    request: UpdateMarcacionCategoryRequest,
    use_case: Annotated[
        UpdateMarcacionCategoryUseCase, Depends(get_update_marcacion_category_use_case)
    ],
):
    try:
        entry = use_case.execute(
            entry_id,
            value=request.value,
            risk_label=request.risk_label,
            active=request.active,
        )
    except MarcacionCategoryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_marcacion_category(
    entry_id: str,
    use_case: Annotated[
        DeleteMarcacionCategoryUseCase, Depends(get_delete_marcacion_category_use_case)
    ],
):
    use_case.execute(entry_id)


def _to_schema(entry: MarcacionCategory) -> MarcacionCategorySchema:
    return MarcacionCategorySchema(
        id=entry.id,
        value=entry.value,
        risk_label=entry.risk_label,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
