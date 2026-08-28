from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.tag_catalog_port import TagCategory, TagEntry
from src.application.use_cases.tag_catalog.create_tag import CreateTagUseCase
from src.application.use_cases.tag_catalog.delete_tag import DeleteTagUseCase
from src.application.use_cases.tag_catalog.list_tags import ListTagsUseCase
from src.application.use_cases.tag_catalog.update_tag import (
    TagNotFoundError,
    UpdateTagUseCase,
)
from src.infrastructure.entrypoint.api.factories.tag_catalog_factory import (
    get_create_tag_use_case,
    get_delete_tag_use_case,
    get_list_tags_use_case,
    get_update_tag_use_case,
)
from src.infrastructure.entrypoint.api.schemas import (
    CreateTagRequest,
    TagEntrySchema,
    UpdateTagRequest,
)

router = APIRouter(prefix="/tag-catalog", tags=["tag-catalog"])


@router.get("", response_model=list[TagEntrySchema])
def list_tags(
    category: TagCategory,
    use_case: Annotated[ListTagsUseCase, Depends(get_list_tags_use_case)],
    active_only: bool = False,
):
    return [
        _to_schema(entry)
        for entry in use_case.execute(category, active_only=active_only)
    ]


@router.post("", response_model=TagEntrySchema, status_code=status.HTTP_201_CREATED)
def create_tag(
    request: CreateTagRequest,
    use_case: Annotated[CreateTagUseCase, Depends(get_create_tag_use_case)],
):
    return _to_schema(use_case.execute(request.category, request.value))


@router.patch("/{category}/{tag_id}", response_model=TagEntrySchema)
def update_tag(
    category: TagCategory,
    tag_id: str,
    request: UpdateTagRequest,
    use_case: Annotated[UpdateTagUseCase, Depends(get_update_tag_use_case)],
):
    try:
        entry = use_case.execute(
            category, tag_id, value=request.value, active=request.active
        )
    except TagNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_schema(entry)


@router.delete("/{category}/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    category: TagCategory,
    tag_id: str,
    use_case: Annotated[DeleteTagUseCase, Depends(get_delete_tag_use_case)],
):
    use_case.execute(category, tag_id)


def _to_schema(entry: TagEntry) -> TagEntrySchema:
    return TagEntrySchema(
        id=entry.id,
        category=entry.category,
        value=entry.value,
        active=entry.active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
