from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.modus_operandi_library_port import ModusOperandiLibraryEntry
from src.application.use_cases.modus_operandi_library.create_modus_operandi_library_entry import (
    CreateModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.delete_modus_operandi_library_entry import (
    DeleteModusOperandiLibraryEntryUseCase,
)
from src.application.use_cases.modus_operandi_library.list_modus_operandi_library_entries import (
    ListModusOperandiLibraryEntriesUseCase,
)
from src.application.use_cases.modus_operandi_library.update_modus_operandi_library_entry import (
    ModusOperandiLibraryEntryNotFoundError,
    UpdateModusOperandiLibraryEntryUseCase,
)
from src.infrastructure.entrypoint.api.factories.modus_operandi_library_factory import (
    get_create_modus_operandi_library_entry_use_case,
    get_delete_modus_operandi_library_entry_use_case,
    get_list_modus_operandi_library_entries_use_case,
    get_update_modus_operandi_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateModusOperandiLibraryEntryRequest,
    ModusOperandiLibraryEntrySchema,
    UpdateModusOperandiLibraryEntryRequest,
)

router = APIRouter(prefix="/library/modus-operandi", tags=["knowledge-library"])


@router.get("", response_model=list[ModusOperandiLibraryEntrySchema])
def list_modus_operandi_library_entries(
    use_case: Annotated[
        ListModusOperandiLibraryEntriesUseCase,
        Depends(get_list_modus_operandi_library_entries_use_case),
    ],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post(
    "", response_model=ModusOperandiLibraryEntrySchema, status_code=status.HTTP_201_CREATED
)
def create_modus_operandi_library_entry(
    request: CreateModusOperandiLibraryEntryRequest,
    use_case: Annotated[
        CreateModusOperandiLibraryEntryUseCase,
        Depends(get_create_modus_operandi_library_entry_use_case),
    ],
):
    return _to_schema(
        use_case.execute(
            request.title,
            request.narrative,
            request.taxonomy_library_id,
            request.evolved_variables,
        )
    )


@router.patch("/{entry_id}", response_model=ModusOperandiLibraryEntrySchema)
def update_modus_operandi_library_entry(
    entry_id: str,
    request: UpdateModusOperandiLibraryEntryRequest,
    use_case: Annotated[
        UpdateModusOperandiLibraryEntryUseCase,
        Depends(get_update_modus_operandi_library_entry_use_case),
    ],
):
    try:
        entry = use_case.execute(
            entry_id,
            title=request.title,
            narrative=request.narrative,
            taxonomy_library_id=request.taxonomy_library_id,
            evolved_variables=request.evolved_variables,
            active=request.active,
        )
    except ModusOperandiLibraryEntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_modus_operandi_library_entry(
    entry_id: str,
    use_case: Annotated[
        DeleteModusOperandiLibraryEntryUseCase,
        Depends(get_delete_modus_operandi_library_entry_use_case),
    ],
):
    use_case.execute(entry_id)


def _to_schema(entry: ModusOperandiLibraryEntry) -> ModusOperandiLibraryEntrySchema:
    return ModusOperandiLibraryEntrySchema(
        id=entry.id,
        title=entry.title,
        narrative=entry.narrative,
        taxonomy_library_id=entry.taxonomy_library_id,
        evolved_variables=entry.evolved_variables,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
