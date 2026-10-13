from __future__ import annotations

from pydantic import BaseModel, Field

from src.domain.configurations.entities import FlagType


class TaxonomySchema(BaseModel):
    id: str = ""
    code: str
    name: str
    description: str = ""
    variables: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    active: bool = True
    segmento: str = ""


class ModusOperandiSchema(BaseModel):
    id: str = ""
    title: str
    narrative: str = ""
    taxonomy_id: str
    evolved_variables: list[str] = Field(default_factory=list)
    active: bool = True
    segmento: str = ""


class FlagSchema(BaseModel):
    id: str = ""
    flag_type: FlagType
    name: str
    description: str = ""
    evolved_variables: list[str] = Field(default_factory=list)
    modus_operandi_ids: list[str] = Field(default_factory=list)
    segmento: str = ""


class ExampleCaseSchema(BaseModel):
    id: str = ""
    text: str
    modus_operandi_id: str
    taxonomy_id: str
    segmento: str = ""
