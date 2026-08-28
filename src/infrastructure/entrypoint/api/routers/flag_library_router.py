from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.flag_library_port import FlagLibraryEntry
from src.application.use_cases.flag_library.create_flag_library_entry import (
    CreateFlagLibraryEntryUseCase,
)
from src.application.use_cases.flag_library.delete_flag_library_entry import (
    DeleteFlagLibraryEntryUseCase,
)
from src.application.use_cases.flag_library.list_flag_library_entries import (
    ListFlagLibraryEntriesUseCase,
)
from src.application.use_cases.flag_library.update_flag_library_entry import (
    FlagLibraryEntryNotFoundError,
    UpdateFlagLibraryEntryUseCase,
)
from src.infrastructure.entrypoint.api.factories.flag_library_factory import (
    get_create_flag_library_entry_use_case,
    get_delete_flag_library_entry_use_case,
    get_list_flag_library_entries_use_case,
    get_update_flag_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateFlagLibraryEntryRequest,
    FlagLibraryEntrySchema,
    UpdateFlagLibraryEntryRequest,
)

router = APIRouter(prefix="/library/flags", tags=["knowledge-library"])


@router.get("", response_model=list[FlagLibraryEntrySchema])
def list_flag_library_entries(
    use_case: Annotated[
        ListFlagLibraryEntriesUseCase, Depends(get_list_flag_library_entries_use_case)
    ],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post("", response_model=FlagLibraryEntrySchema, status_code=status.HTTP_201_CREATED)
def create_flag_library_entry(
    request: CreateFlagLibraryEntryRequest,
    use_case: Annotated[
        CreateFlagLibraryEntryUseCase, Depends(get_create_flag_library_entry_use_case)
    ],
):
    return _to_schema(
        use_case.execute(
            request.flag_type,
            request.name,
            request.description,
            request.evolved_variables,
            request.modus_operandi_library_ids,
        )
    )


@router.patch("/{entry_id}", response_model=FlagLibraryEntrySchema)
def update_flag_library_entry(
    entry_id: str,
    request: UpdateFlagLibraryEntryRequest,
    use_case: Annotated[
        UpdateFlagLibraryEntryUseCase, Depends(get_update_flag_library_entry_use_case)
    ],
):
    try:
        entry = use_case.execute(
            entry_id,
            flag_type=request.flag_type,
            name=request.name,
            description=request.description,
            evolved_variables=request.evolved_variables,
            modus_operandi_library_ids=request.modus_operandi_library_ids,
            active=request.active,
        )
    except FlagLibraryEntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flag_library_entry(
    entry_id: str,
    use_case: Annotated[
        DeleteFlagLibraryEntryUseCase, Depends(get_delete_flag_library_entry_use_case)
    ],
):
    use_case.execute(entry_id)


def _to_schema(entry: FlagLibraryEntry) -> FlagLibraryEntrySchema:
    return FlagLibraryEntrySchema(
        id=entry.id,
        flag_type=entry.flag_type,
        name=entry.name,
        description=entry.description,
        evolved_variables=entry.evolved_variables,
        modus_operandi_library_ids=entry.modus_operandi_library_ids,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
