from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.channel_library_port import ChannelLibraryEntry
from src.application.use_cases.channel_library.create_channel_library_entry import (
    CreateChannelLibraryEntryUseCase,
)
from src.application.use_cases.channel_library.delete_channel_library_entry import (
    DeleteChannelLibraryEntryUseCase,
)
from src.application.use_cases.channel_library.list_channel_library_entries import (
    ListChannelLibraryEntriesUseCase,
)
from src.application.use_cases.channel_library.update_channel_library_entry import (
    ChannelLibraryEntryNotFoundError,
    UpdateChannelLibraryEntryUseCase,
)
from src.infrastructure.entrypoint.api.factories.channel_library_factory import (
    get_create_channel_library_entry_use_case,
    get_delete_channel_library_entry_use_case,
    get_list_channel_library_entries_use_case,
    get_update_channel_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    ChannelLibraryEntrySchema,
    CreateChannelLibraryEntryRequest,
    UpdateChannelLibraryEntryRequest,
)

router = APIRouter(prefix="/library/channels", tags=["knowledge-library"])


@router.get("", response_model=list[ChannelLibraryEntrySchema])
def list_channel_library_entries(
    use_case: Annotated[
        ListChannelLibraryEntriesUseCase,
        Depends(get_list_channel_library_entries_use_case),
    ],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post(
    "", response_model=ChannelLibraryEntrySchema, status_code=status.HTTP_201_CREATED
)
def create_channel_library_entry(
    request: CreateChannelLibraryEntryRequest,
    use_case: Annotated[
        CreateChannelLibraryEntryUseCase,
        Depends(get_create_channel_library_entry_use_case),
    ],
):
    return _to_schema(use_case.execute(request.code, request.name, request.description))


@router.patch("/{entry_id}", response_model=ChannelLibraryEntrySchema)
def update_channel_library_entry(
    entry_id: str,
    request: UpdateChannelLibraryEntryRequest,
    use_case: Annotated[
        UpdateChannelLibraryEntryUseCase,
        Depends(get_update_channel_library_entry_use_case),
    ],
):
    try:
        entry = use_case.execute(
            entry_id,
            code=request.code,
            name=request.name,
            description=request.description,
            active=request.active,
        )
    except ChannelLibraryEntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel_library_entry(
    entry_id: str,
    use_case: Annotated[
        DeleteChannelLibraryEntryUseCase,
        Depends(get_delete_channel_library_entry_use_case),
    ],
):
    use_case.execute(entry_id)


def _to_schema(entry: ChannelLibraryEntry) -> ChannelLibraryEntrySchema:
    return ChannelLibraryEntrySchema(
        id=entry.id,
        code=entry.code,
        name=entry.name,
        description=entry.description,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
