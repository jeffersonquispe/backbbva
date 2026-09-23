from __future__ import annotations

import re
from typing import Annotated

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status

from src.application.ports.local_auth_port import LocalRole, LocalUser
from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType, VectorStoreInstance, VectorStoreInstanceAsset,
)
from src.application.use_cases.vector_store_instances.create_vector_store_instance import DuplicateVectorStoreInstanceNameError
from src.application.use_cases.vector_store_instances.create_vector_store_instance import CreateVectorStoreInstanceUseCase
from src.application.use_cases.vector_store_instances.manage_vector_store_instance import VectorStoreInstanceNotFoundError
from src.application.use_cases.vector_store_instances.knowledge_graph import KnowledgeGraphService
from src.infrastructure.entrypoint.api.factories.flag_library_factory import get_flag_library_repository
from src.infrastructure.entrypoint.api.factories.modus_operandi_library_factory import get_modus_operandi_library_repository
from src.infrastructure.entrypoint.api.factories.similar_case_library_factory import get_similar_case_library_repository
from src.infrastructure.entrypoint.api.factories.taxonomy_library_factory import get_taxonomy_library_repository
from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import (
    get_add_vector_store_document_use_case, get_create_vector_store_instance_use_case,
    get_list_vector_store_instances_use_case, get_remove_vector_store_document_use_case,
    get_update_vector_store_instance_use_case,
)
from src.infrastructure.entrypoint.api.routers.auth_router import get_current_user
from src.infrastructure.entrypoint.api.schemas import (
    AddVectorStoreDocumentRequest, CreateVectorStoreInstanceRequest,
    UpdateVectorStoreInstanceRequest, VectorStoreDocumentSchema, VectorStoreInstanceSchema,
)

router = APIRouter(prefix="/vector-store-instances", tags=["vector-store-instances"])
_WRITERS = (LocalRole.MANAGER, LocalRole.CHANNEL_MANAGER, LocalRole.DATA_ANALYST)


def _require_writer(user: LocalUser) -> None:
    if user.role not in _WRITERS:
        raise HTTPException(status_code=403, detail="Role is not permitted to manage vector-store instances")


def _instance_schema(instance: VectorStoreInstance) -> VectorStoreInstanceSchema:
    return VectorStoreInstanceSchema(**instance.__dict__)


def _document_schema(asset: VectorStoreInstanceAsset) -> VectorStoreDocumentSchema:
    return VectorStoreDocumentSchema(
        relation_id=asset.relation_id, asset_type=asset.asset_type,
        asset_id=asset.asset_id, asset_version=asset.asset_version,
    )


def _graph() -> KnowledgeGraphService:
    from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import get_vector_store_instance_repository
    return KnowledgeGraphService(
        instances=get_vector_store_instance_repository(),
        taxonomies=get_taxonomy_library_repository(),
        modus_operandi=get_modus_operandi_library_repository(),
        flags=get_flag_library_repository(),
        similar_cases=get_similar_case_library_repository(),
    )


@router.get("", response_model=list[VectorStoreInstanceSchema])
def list_instances(user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_writer(user)
    return [_instance_schema(item) for item in get_list_vector_store_instances_use_case().execute()]


@router.post("", response_model=VectorStoreInstanceSchema, status_code=status.HTTP_201_CREATED)
def create_instance(
    request: CreateVectorStoreInstanceRequest,
    user: Annotated[LocalUser, Depends(get_current_user)],
    use_case: Annotated[CreateVectorStoreInstanceUseCase, Depends(get_create_vector_store_instance_use_case)],
):
    _require_writer(user)
    try:
        instance = use_case.execute(
            name=request.name, description=request.description, created_by=user.name, assets=[]
        )
    except DuplicateVectorStoreInstanceNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _instance_schema(instance)


@router.patch("/{instance_id}", response_model=VectorStoreInstanceSchema)
def update_instance(instance_id: str, request: UpdateVectorStoreInstanceRequest, user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_writer(user)
    try:
        return _instance_schema(get_update_vector_store_instance_use_case().execute(
            instance_id, name=request.name, description=request.description, actor=user.name
        ))
    except VectorStoreInstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{instance_id}/documents", response_model=list[VectorStoreDocumentSchema])
def list_instance_documents(instance_id: str, user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_writer(user)
    from src.infrastructure.entrypoint.api.factories.vector_store_instance_factory import get_vector_store_instance_repository
    if get_vector_store_instance_repository().get(instance_id) is None:
        raise HTTPException(status_code=404, detail="Vector store instance not found")
    return [_document_schema(asset) for asset in get_vector_store_instance_repository().list_assets(instance_id)]


@router.post("/{instance_id}/documents/preflight")
def preview_add_instance_document(instance_id: str, request: AddVectorStoreDocumentRequest, user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_writer(user)
    try:
        impacts = _graph().preview_add(instance_id, request.asset_type, request.asset_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"instance_id": instance_id, "will_add": [
        {"asset_type": item.asset_type, "asset_id": item.asset_id, "origin": item.origin}
        for item in impacts
    ]}


@router.post("/{instance_id}/documents", response_model=list[VectorStoreDocumentSchema], status_code=status.HTTP_201_CREATED)
def add_instance_document(instance_id: str, request: AddVectorStoreDocumentRequest, user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_writer(user)
    try:
        assets = _graph().attach(instance_id, request.asset_type, request.asset_id)
        # A relation change is an audited edit of the administrable instance.
        get_update_vector_store_instance_use_case().execute(
            instance_id, name=None, description=None, actor=user.name
        )
    except VectorStoreInstanceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            raise HTTPException(status_code=409, detail="Document is already related to this instance") from exc
        raise
    return [_document_schema(asset) for asset in assets]


@router.delete("/{instance_id}/documents/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_instance_document(instance_id: str, relation_id: str, user: Annotated[LocalUser, Depends(get_current_user)]):
    _require_writer(user)
    try:
        get_remove_vector_store_document_use_case().execute(instance_id, relation_id, actor=user.name)
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
        raise HTTPException(status_code=422, detail=f"Invalid regular expression: {exc}") from exc
    results = [item for item in _all_assets() if asset_type is None or item["asset_type"] == asset_type]
    if pattern:
        results = [item for item in results if pattern.search(item["name"])]
    return results


def _asset_exists(asset_type: KnowledgeAssetType, asset_id: str) -> bool:
    return any(item["asset_type"] == asset_type and item["asset_id"] == asset_id for item in _all_assets())


def _all_assets() -> list[dict[str, object]]:
    assets: list[dict[str, object]] = []
    assets.extend({"asset_type": KnowledgeAssetType.TAXONOMY, "asset_id": item.id, "name": item.name} for item in get_taxonomy_library_repository().list())
    assets.extend({"asset_type": KnowledgeAssetType.MODUS_OPERANDI, "asset_id": item.id, "name": item.title} for item in get_modus_operandi_library_repository().list())
    assets.extend({"asset_type": KnowledgeAssetType.RED_FLAG if item.flag_type.value == "red" else KnowledgeAssetType.YELLOW_FLAG, "asset_id": item.id, "name": item.name} for item in get_flag_library_repository().list())
    assets.extend({"asset_type": KnowledgeAssetType.SIMILAR_CASE, "asset_id": item.id, "name": item.text} for item in get_similar_case_library_repository().list())
    return assets
