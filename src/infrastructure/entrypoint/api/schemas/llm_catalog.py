from __future__ import annotations

from pydantic import BaseModel


class LLMCatalogEntrySchema(BaseModel):
    name: str
    deployment: str


class LLMElementSchema(BaseModel):
    element: str
    group: str
    default_deployment: str


class LLMCatalogResponse(BaseModel):
    entries: list[LLMCatalogEntrySchema]
    elements: list[LLMElementSchema]
