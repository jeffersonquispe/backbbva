from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.taxonomy_library_port import TaxonomyLibraryEntry
from src.application.use_cases.taxonomy_library.create_taxonomy_library_entry import (
    CreateTaxonomyLibraryEntryUseCase,
)
from src.application.use_cases.taxonomy_library.delete_taxonomy_library_entry import (
    DeleteTaxonomyLibraryEntryUseCase,
)
from src.application.use_cases.taxonomy_library.list_taxonomy_library_entries import (
    ListTaxonomyLibraryEntriesUseCase,
)
from src.application.use_cases.taxonomy_library.update_taxonomy_library_entry import (
    TaxonomyLibraryEntryNotFoundError,
    UpdateTaxonomyLibraryEntryUseCase,
)
from src.infrastructure.entrypoint.api.factories.taxonomy_library_factory import (
    get_create_taxonomy_library_entry_use_case,
    get_delete_taxonomy_library_entry_use_case,
    get_list_taxonomy_library_entries_use_case,
    get_update_taxonomy_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateTaxonomyLibraryEntryRequest,
    TaxonomyLibraryEntrySchema,
    UpdateTaxonomyLibraryEntryRequest,
)

router = APIRouter(prefix="/library/taxonomies", tags=["knowledge-library"])


@router.get("", response_model=list[TaxonomyLibraryEntrySchema])
def list_taxonomy_library_entries(
    use_case: Annotated[
        ListTaxonomyLibraryEntriesUseCase, Depends(get_list_taxonomy_library_entries_use_case)
    ],
    active_only: bool = False,
):
    return [_to_schema(entry) for entry in use_case.execute(active_only=active_only)]


@router.post(
    "", response_model=TaxonomyLibraryEntrySchema, status_code=status.HTTP_201_CREATED
)
def create_taxonomy_library_entry(
    request: CreateTaxonomyLibraryEntryRequest,
    use_case: Annotated[
        CreateTaxonomyLibraryEntryUseCase, Depends(get_create_taxonomy_library_entry_use_case)
    ],
):
    return _to_schema(
        use_case.execute(
            request.code,
            request.name,
            request.description,
            request.variables,
            request.examples,
        )
    )


@router.patch("/{entry_id}", response_model=TaxonomyLibraryEntrySchema)
def update_taxonomy_library_entry(
    entry_id: str,
    request: UpdateTaxonomyLibraryEntryRequest,
    use_case: Annotated[
        UpdateTaxonomyLibraryEntryUseCase, Depends(get_update_taxonomy_library_entry_use_case)
    ],
):
    try:
        entry = use_case.execute(
            entry_id,
            code=request.code,
            name=request.name,
            description=request.description,
            variables=request.variables,
            examples=request.examples,
            active=request.active,
        )
    except TaxonomyLibraryEntryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_taxonomy_library_entry(
    entry_id: str,
    use_case: Annotated[
        DeleteTaxonomyLibraryEntryUseCase, Depends(get_delete_taxonomy_library_entry_use_case)
    ],
):
    use_case.execute(entry_id)


def _to_schema(entry: TaxonomyLibraryEntry) -> TaxonomyLibraryEntrySchema:
    return TaxonomyLibraryEntrySchema(
        id=entry.id,
        code=entry.code,
        name=entry.name,
        description=entry.description,
        variables=entry.variables,
        examples=entry.examples,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
