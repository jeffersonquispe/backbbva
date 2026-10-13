from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.application.ports.vector_store_instance_port import KnowledgeAssetType

# --- Vector-store instances -------------------------------------------------


class VectorStoreInstanceSchema(BaseModel):
    id: str
    version: int
    name: str
    description: str
    created_at: datetime
    created_by: str
    updated_at: datetime | None
    updated_by: str | None
    promoted_version: int | None = None
    promoted_at: datetime | None = None
    promoted_by: str | None = None


class CreateVectorStoreInstanceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UpdateVectorStoreInstanceRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class VectorStoreDocumentSchema(BaseModel):
    relation_id: str
    asset_type: KnowledgeAssetType
    asset_id: str
    asset_version: int


class AddVectorStoreDocumentRequest(BaseModel):
    asset_type: KnowledgeAssetType
    asset_id: str = Field(..., min_length=1)
    # The asset version is explicit so a later edit can add a new immutable
    # revision alongside the original relation.
    asset_version: int = Field(default=1, ge=1)
