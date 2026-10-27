from __future__ import annotations

import re
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.application.errors import ConflictError, NotFoundError, ValidationError
from src.application.ports.fraud_knowledge_port import DocumentType, SearchPipeline
from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceAsset,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    VectorStoreGenerationUnavailableError,
)
from src.application.use_cases.vector_store_instances.build_vector_store_generation import (
    BuildVectorStoreGenerationUseCase,
    EmptyVectorStoreInstanceError,
)
from src.application.use_cases.vector_store_instances.create_vector_store_instance import (
    CreateVectorStoreInstanceUseCase,
    DuplicateVectorStoreInstanceNameError,
)
from src.application.use_cases.vector_store_instances.knowledge_graph import (
    KnowledgeGraphService,
)
from src.application.use_cases.vector_store_instances.list_vector_store_instances import (
    VectorStoreGenerationView,
    VectorStoreInstanceSummary,
)
from src.application.use_cases.vector_store_instances.manage_vector_store_instance import (
    VectorStoreInstanceNotFoundError,
)
from src.infrastructure.entrypoint.api.factories.flag_library_factory import (
    get_flag_library_repository,
)
from src.infrastructure.entrypoint.api.factories.fraud_knowledge_factory import (
    get_search_fraud_knowledge_use_case,
)
from src.infrastructure.entrypoint.api.factories.modus_operandi_library_factory import (
    get_modus_operandi_library_repository,
)
from src.infrastructure.entrypoint.api.factories.similar_case_library_factory import (
    get_similar_case_library_repository,
)
from src.infrastructure.entrypoint.api.factories.taxonomy_library_factory import (
    get_taxonomy_library_repository,
)
from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import (
    get_build_vector_store_generation_use_case,
    get_create_vector_store_instance_use_case,
    get_knowledge_graph_service,
    get_list_vector_store_instances_use_case,
    get_remove_vector_store_document_use_case,
    get_update_vector_store_instance_use_case,
    get_vector_store_instance_repository,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas import (
    AddVectorStoreDocumentRequest,
    BuildVectorStoreGenerationResponse,
    CreateVectorStoreInstanceRequest,
    UpdateVectorStoreInstanceRequest,
    VectorStoreDocumentSchema,
    VectorStoreGenerationSchema,
    VectorStoreInstanceSchema,
)

router = APIRouter(prefix="/vector-store-instances", tags=["vector-store-instances"])
_WRITERS = (LocalRole.MANAGER, LocalRole.CHANNEL_MANAGER, LocalRole.DATA_ANALYST)


def _require_writer(user: LocalUser) -> None:
    if user.role not in _WRITERS:
        raise HTTPException(
            status_code=403,
            detail="Role is not permitted to manage vector-store instances",
        )


def _instance_schema(instance: VectorStoreInstance) -> VectorStoreInstanceSchema:
    return _summary_schema(
        get_list_vector_store_instances_use_case().summarize(instance)
    )


def _summary_schema(summary: VectorStoreInstanceSummary) -> VectorStoreInstanceSchema:
    return VectorStoreInstanceSchema(
        **summary.instance.__dict__,
        latest_generation=summary.latest_ready_generation,
        production_generations=list(summary.production_generations),
    )


def _generation_schema(view: VectorStoreGenerationView, fingerprint: str | None = None) -> VectorStoreGenerationSchema:
    generation = view.generation
    return VectorStoreGenerationSchema(
        instance_id=generation.instance_id,
        generation=generation.generation,
        status=generation.status.value,
        built_by=generation.built_by,
        created_at=generation.created_at,
        ready_at=generation.ready_at,
        retired_at=generation.retired_at,
        fingerprint=generation.fingerprint,
        document_count=generation.document_count,
        error=generation.error,
        migrated=generation.migrated,
        in_production=view.in_production,
        pinned_by=list(view.pinned_by),
        matches_manifest=(generation.fingerprint == fingerprint if fingerprint is not None else None),
    )


def _document_schema(asset: VectorStoreInstanceAsset) -> VectorStoreDocumentSchema:
    return VectorStoreDocumentSchema(
        relation_id=asset.relation_id,
        asset_type=asset.asset_type,
        asset_id=asset.asset_id,
        asset_version=asset.asset_version,
    )


def _graph() -> KnowledgeGraphService:
    return get_knowledge_graph_service()


@router.get("/{instance_id}/query")
def query_vector_store_instance(
    instance_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    query: str = Query(min_length=1, max_length=2000),
    document_type: DocumentType = DocumentType.MODUS_OPERANDI,
    pipeline: SearchPipeline = SearchPipeline.BALANCED,
    top_k: int = Query(default=5, ge=1, le=50),
    generation: int | None = Query(default=None, ge=1),
):
    """Runs a retrieval query against one generation of an instance (its
    newest READY one when ``generation`` is omitted)."""
    _require_writer(user)
    try:
        hits = get_search_fraud_knowledge_use_case().execute(
            query,
            pipeline=pipeline,
            vector_store_id=instance_id,
            vector_store_generation=generation,
            document_type=document_type,
            top_k=top_k,
        )
    except VectorStoreGenerationUnavailableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return [
        {
            "id": str(hit.document.id),
            "type": hit.document.type.value,
            "text": hit.document.text,
            "score": hit.score,
            "vector_store_id": hit.document.vector_store_id,
            "vector_store_version": hit.document.vector_store_version,
        }
        for hit in hits
    ]


@router.get("", response_model=list[VectorStoreInstanceSchema])
def list_instances(user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_writer(user)
    return [
        _summary_schema(item)
        for item in get_list_vector_store_instances_use_case().execute()
    ]


@router.post(
    "", response_model=VectorStoreInstanceSchema, status_code=status.HTTP_201_CREATED
)
def create_instance(
    request: CreateVectorStoreInstanceRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        CreateVectorStoreInstanceUseCase,
        Depends(get_create_vector_store_instance_use_case),
    ],
):
    _require_writer(user)
    try:
        instance = use_case.execute(
            name=request.name,
            description=request.description,
            created_by=user.name,
            assets=[],
        )
    except DuplicateVectorStoreInstanceNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _summary_schema(VectorStoreInstanceSummary(instance, None))


@router.patch("/{instance_id}", response_model=VectorStoreInstanceSchema)
def update_instance(
    instance_id: str,
    request: UpdateVectorStoreInstanceRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_writer(user)
    try:
        return _instance_schema(
            get_update_vector_store_instance_use_case().execute(
                instance_id,
                name=request.name,
                description=request.description,
                actor=user.name,
            )
        )
    except VectorStoreInstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/{instance_id}/generations", response_model=list[VectorStoreGenerationSchema]
)
def list_instance_generations(
    instance_id: str, user: Annotated[LocalUser, Depends(get_current_user)]
):
    """Every generation of this instance, newest first, with whether the
    active configuration searches it and which saved versions pin it."""
    _require_writer(user)
    if get_vector_store_instance_repository().get(instance_id) is None:
        raise HTTPException(status_code=404, detail="Vector store instance not found")
    try:
        fingerprint = get_build_vector_store_generation_use_case().fingerprint(instance_id)
    except (NotFoundError, ValidationError):
        fingerprint = "invalid"
    return [
        _generation_schema(view, fingerprint)
        for view in get_list_vector_store_instances_use_case().generations(
            instance_id
        )
    ]


@router.post(
    "/{instance_id}/generations", response_model=BuildVectorStoreGenerationResponse
)
def build_instance_generation(
    instance_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[
        BuildVectorStoreGenerationUseCase,
        Depends(get_build_vector_store_generation_use_case),
    ],
):
    """Loads this instance's current manifest into OpenSearch as a new
    immutable generation (or returns the READY one with the same content).
    Production is not affected: it searches the generation the active
    configuration pins, which changes only through an approved deploy
    request."""
    _require_writer(user)
    try:
        result = use_case.execute(instance_id, actor=user.name)
    except (VectorStoreInstanceNotFoundError, NotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (EmptyVectorStoreInstanceError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    view = next(
        item
        for item in get_list_vector_store_instances_use_case().generations(instance_id)
        if item.generation.generation == result.generation.generation
    )
    return BuildVectorStoreGenerationResponse(
        **_generation_schema(view).model_dump(), built=result.built
    )


@router.get("/{instance_id}/documents", response_model=list[VectorStoreDocumentSchema])
def list_instance_documents(
    instance_id: str, user: Annotated[LocalUser, Depends(get_current_user)]
):
    _require_writer(user)
    if get_vector_store_instance_repository().get(instance_id) is None:
        raise HTTPException(status_code=404, detail="Vector store instance not found")
    return [
        _document_schema(asset)
        for asset in get_vector_store_instance_repository().list_assets(instance_id)
    ]


@router.post("/{instance_id}/documents/preflight")
def preview_add_instance_document(
    instance_id: str,
    request: AddVectorStoreDocumentRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_writer(user)
    try:
        impacts = _graph().preview_add(
            instance_id, request.asset_type, request.asset_id
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "instance_id": instance_id,
        "will_add": [
            {
                "asset_type": item.asset_type,
                "asset_id": item.asset_id,
                "origin": item.origin,
            }
            for item in impacts
        ],
    }


@router.post(
    "/{instance_id}/documents",
    response_model=list[VectorStoreDocumentSchema],
    status_code=status.HTTP_201_CREATED,
)
def add_instance_document(
    instance_id: str,
    request: AddVectorStoreDocumentRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_writer(user)
    try:
        assets = _graph().attach(instance_id, request.asset_type, request.asset_id)
        # A relation change is an audited edit of the administrable instance.
        get_update_vector_store_instance_use_case().execute(
            instance_id, name=None, description=None, actor=user.name
        )
    except VectorStoreInstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            == "ConditionalCheckFailedException"
        ):
            raise HTTPException(
                status_code=409, detail="Document is already related to this instance"
            ) from exc
        raise
    return [_document_schema(asset) for asset in assets]


@router.delete(
    "/{instance_id}/documents/{relation_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_instance_document(
    instance_id: str,
    relation_id: str,
    user: Annotated[LocalUser, Depends(get_current_user)],
):
    _require_writer(user)
    try:
        get_remove_vector_store_document_use_case().execute(
            instance_id, relation_id, actor=user.name
        )
    except VectorStoreInstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/documents/search")
def search_library_documents(
    user: Annotated[LocalUser, Depends(get_current_user)],
    asset_type: KnowledgeAssetType | None = None,
    query: str = "",
):
    """Searches library document names by text or regular expression.

    This endpoint only discovers source assets for the aggregator; it does
    not index or embed anything.
    """
    _require_writer(user)
    try:
        pattern = re.compile(query, re.IGNORECASE) if query else None
    except re.error as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid regular expression: {exc}"
        ) from exc
    results = [
        item
        for item in _all_assets()
        if asset_type is None or item["asset_type"] == asset_type
    ]
    if pattern:
        results = [item for item in results if pattern.search(item["name"])]
    return results


def _asset_exists(asset_type: KnowledgeAssetType, asset_id: str) -> bool:
    return any(
        item["asset_type"] == asset_type and item["asset_id"] == asset_id
        for item in _all_assets()
    )


def _all_assets() -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    assets.extend(
        {
            "asset_type": KnowledgeAssetType.TAXONOMY,
            "asset_id": item.id,
            "name": item.name,
        }
        for item in get_taxonomy_library_repository().list()
    )
    assets.extend(
        {
            "asset_type": KnowledgeAssetType.MODUS_OPERANDI,
            "asset_id": item.id,
            "name": item.title,
        }
        for item in get_modus_operandi_library_repository().list()
    )
    assets.extend(
        {
            "asset_type": KnowledgeAssetType.RED_FLAG
            if item.flag_type.value == "red"
            else KnowledgeAssetType.YELLOW_FLAG,
            "asset_id": item.id,
            "name": item.name,
        }
        for item in get_flag_library_repository().list()
    )
    assets.extend(
        {
            "asset_type": KnowledgeAssetType.SIMILAR_CASE,
            "asset_id": item.id,
            "name": item.text,
        }
        for item in get_similar_case_library_repository().list()
    )
    return assets
