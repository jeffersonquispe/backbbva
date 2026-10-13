from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.taxonomy_library_port import TaxonomyLibraryEntry
from src.application.ports.vector_store_instance_port import KnowledgeAssetType
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
from src.infrastructure.entrypoint.api.authorization import require_library_access
from src.infrastructure.entrypoint.api.factories.flag_library_factory import (
    get_flag_library_repository,
)
from src.infrastructure.entrypoint.api.factories.modus_operandi_library_factory import (
    get_modus_operandi_library_repository,
)
from src.infrastructure.entrypoint.api.factories.similar_case_library_factory import (
    get_similar_case_library_repository,
)
from src.infrastructure.entrypoint.api.factories.taxonomy_library_factory import (
    get_create_taxonomy_library_entry_use_case,
    get_delete_taxonomy_library_entry_use_case,
    get_list_taxonomy_library_entries_use_case,
    get_update_taxonomy_library_entry_use_case,
)
from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import (
    get_knowledge_graph_service,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateTaxonomyLibraryEntryRequest,
    TaxonomyLibraryEntrySchema,
    UpdateTaxonomyLibraryEntryRequest,
)

router = APIRouter(
    prefix="/library/taxonomies",
    tags=["knowledge-library"],
    dependencies=[Depends(require_library_access)],
)


@router.get("", response_model=list[TaxonomyLibraryEntrySchema])
def list_taxonomy_library_entries(
    use_case: Annotated[
        ListTaxonomyLibraryEntriesUseCase,
        Depends(get_list_taxonomy_library_entries_use_case),
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
        CreateTaxonomyLibraryEntryUseCase,
        Depends(get_create_taxonomy_library_entry_use_case),
    ],
):
    entry = use_case.execute(
        request.code,
        request.name,
        request.description,
        request.variables,
        request.examples,
    )
    get_knowledge_graph_service().synchronize_new_asset(
        KnowledgeAssetType.TAXONOMY, entry.id
    )
    return _to_schema(entry)


@router.patch("/{entry_id}", response_model=TaxonomyLibraryEntrySchema)
def update_taxonomy_library_entry(
    entry_id: str,
    request: UpdateTaxonomyLibraryEntryRequest,
    use_case: Annotated[
        UpdateTaxonomyLibraryEntryUseCase,
        Depends(get_update_taxonomy_library_entry_use_case),
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
        DeleteTaxonomyLibraryEntryUseCase,
        Depends(get_delete_taxonomy_library_entry_use_case),
    ],
):
    # A taxonomy is the only removable root.  Descendants are removed in a
    # deterministic order; shared flags are detached and retained for their
    # remaining modus operandi instead of being accidentally destroyed.
    # Remove the instance relations first, while the graph still has all
    # parentage needed to calculate the recursive closure.
    get_knowledge_graph_service().detach_tree_from_all_instances(
        KnowledgeAssetType.TAXONOMY, entry_id
    )
    modus_operandi = get_modus_operandi_library_repository()
    similar_cases = get_similar_case_library_repository()
    flags = get_flag_library_repository()
    descendants = [
        entry
        for entry in modus_operandi.list()
        if entry.taxonomy_library_id == entry_id
    ]
    descendant_ids = {entry.id for entry in descendants}
    for case in similar_cases.list():
        if case.modus_operandi_library_id in descendant_ids:
            similar_cases.delete(case.id)
    for flag in flags.list():
        matching = set(flag.modus_operandi_library_ids) & descendant_ids
        if not matching:
            continue
        remaining = [
            mo_id
            for mo_id in flag.modus_operandi_library_ids
            if mo_id not in descendant_ids
        ]
        if remaining:
            flags.update(flag.id, modus_operandi_library_ids=remaining)
        else:
            flags.delete(flag.id)
    for descendant in descendants:
        modus_operandi.delete(descendant.id)
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
