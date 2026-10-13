from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.application.ports.configuration_port import ResolutionTag
from src.application.ports.marcacion_catalog_port import RiskLabel
from src.application.ports.tag_catalog_port import TagCategory

# --- Tag catalog ---------------------------------------------------------


class TagEntrySchema(BaseModel):
    id: str
    category: TagCategory
    value: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateTagRequest(BaseModel):
    category: TagCategory
    value: str = Field(..., min_length=1, max_length=200)


class UpdateTagRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None


# --- Marcación catalog -----------------------------------------------------


class MarcacionCategorySchema(BaseModel):
    id: str
    value: str
    risk_label: RiskLabel
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateMarcacionCategoryRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    risk_label: RiskLabel


class UpdateMarcacionCategoryRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    risk_label: RiskLabel | None = None
    active: bool | None = None


# --- Resolution method catalog ------------------------------------------


class ResolutionMethodSchema(BaseModel):
    id: str
    value: str
    resolution_tag: ResolutionTag
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateResolutionMethodRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    resolution_tag: ResolutionTag


class UpdateResolutionMethodRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    resolution_tag: ResolutionTag | None = None
    active: bool | None = None


# --- Variable catalog --------------------------------------------------


class VariableSchema(BaseModel):
    id: str
    value: str
    description: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateVariableRequest(BaseModel):
    value: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)


class UpdateVariableRequest(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None
