from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.variable_catalog_port import VariableEntry
from src.application.use_cases.variable_catalog.create_variable import (
    CreateVariableUseCase,
)
from src.application.use_cases.variable_catalog.delete_variable import (
    DeleteVariableUseCase,
)
from src.application.use_cases.variable_catalog.list_variables import (
    ListVariablesUseCase,
)
from src.application.use_cases.variable_catalog.update_variable import (
    UpdateVariableUseCase,
    VariableNotFoundError,
)
from src.infrastructure.entrypoint.api.factories.variable_catalog_factory import (
    get_create_variable_use_case,
    get_delete_variable_use_case,
    get_list_variables_use_case,
    get_update_variable_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateVariableRequest,
    UpdateVariableRequest,
    VariableSchema,
)

router = APIRouter(prefix="/variable-catalog", tags=["variable-catalog"])


@router.get("", response_model=list[VariableSchema])
def list_variables(
    use_case: Annotated[ListVariablesUseCase, Depends(get_list_variables_use_case)],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post("", response_model=VariableSchema, status_code=status.HTTP_201_CREATED)
def create_variable(
    request: CreateVariableRequest,
    use_case: Annotated[CreateVariableUseCase, Depends(get_create_variable_use_case)],
):
    return _to_schema(use_case.execute(request.value, request.description))


@router.patch("/{entry_id}", response_model=VariableSchema)
def update_variable(
    entry_id: str,
    request: UpdateVariableRequest,
    use_case: Annotated[UpdateVariableUseCase, Depends(get_update_variable_use_case)],
):
    try:
        entry = use_case.execute(
            entry_id,
            value=request.value,
            description=request.description,
            active=request.active,
        )
    except VariableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variable(
    entry_id: str,
    use_case: Annotated[DeleteVariableUseCase, Depends(get_delete_variable_use_case)],
):
    use_case.execute(entry_id)


def _to_schema(entry: VariableEntry) -> VariableSchema:
    return VariableSchema(
        id=entry.id,
        value=entry.value,
        description=entry.description,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
