from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.similar_case_library_port import SimilarCaseLibraryEntry
from src.application.use_cases.similar_case_library.create_similar_case_library_entry import (
    CreateSimilarCaseLibraryEntryUseCase,
)
from src.application.use_cases.similar_case_library.delete_similar_case_library_entry import (
    DeleteSimilarCaseLibraryEntryUseCase,
)
from src.application.use_cases.similar_case_library.list_similar_case_library_entries import (
    ListSimilarCaseLibraryEntriesUseCase,
)
from src.application.use_cases.similar_case_library.update_similar_case_library_entry import (
    SimilarCaseLibraryEntryNotFoundError,
    UpdateSimilarCaseLibraryEntryUseCase,
)
from src.infrastructure.entrypoint.api.factories.similar_case_library_factory import (
    get_create_similar_case_library_entry_use_case,
    get_delete_similar_case_library_entry_use_case,
    get_list_similar_case_library_entries_use_case,
    get_update_similar_case_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateSimilarCaseLibraryEntryRequest,
    SimilarCaseLibraryEntrySchema,
    UpdateSimilarCaseLibraryEntryRequest,
)

router = APIRouter(prefix="/library/similar-cases", tags=["knowledge-library"])


@router.get("", response_model=list[SimilarCaseLibraryEntrySchema])
def list_similar_case_library_entries(
    use_case: Annotated[
        ListSimilarCaseLibraryEntriesUseCase,
        Depends(get_list_similar_case_library_entries_use_case),
    ],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post(
    "", response_model=SimilarCaseLibraryEntrySchema, status_code=status.HTTP_201_CREATED
)
def create_similar_case_library_entry(
    request: CreateSimilarCaseLibraryEntryRequest,
    use_case: Annotated[
        CreateSimilarCaseLibraryEntryUseCase,
        Depends(get_create_similar_case_library_entry_use_case),
    ],
):
    return _to_schema(
        use_case.execute(
            request.text, request.modus_operandi_library_id, request.taxonomy_library_id
        )
    )


@router.patch("/{entry_id}", response_model=SimilarCaseLibraryEntrySchema)
def update_similar_case_library_entry(
    entry_id: str,
    request: UpdateSimilarCaseLibraryEntryRequest,
    use_case: Annotated[
        UpdateSimilarCaseLibraryEntryUseCase,
        Depends(get_update_similar_case_library_entry_use_case),
    ],
):
    try:
        entry = use_case.execute(
            entry_id,
            text=request.text,
            modus_operandi_library_id=request.modus_operandi_library_id,
            taxonomy_library_id=request.taxonomy_library_id,
            active=request.active,
        )
    except SimilarCaseLibraryEntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_similar_case_library_entry(
    entry_id: str,
    use_case: Annotated[
        DeleteSimilarCaseLibraryEntryUseCase,
        Depends(get_delete_similar_case_library_entry_use_case),
    ],
):
    use_case.execute(entry_id)


def _to_schema(entry: SimilarCaseLibraryEntry) -> SimilarCaseLibraryEntrySchema:
    return SimilarCaseLibraryEntrySchema(
        id=entry.id,
        text=entry.text,
        modus_operandi_library_id=entry.modus_operandi_library_id,
        taxonomy_library_id=entry.taxonomy_library_id,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
