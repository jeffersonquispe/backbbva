from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from src.domain.configurations.entities import (
    FlagType,
    ResolutionTag,
)
from src.infrastructure.entrypoint.api.schemas.configuration import (
    ShortageBehaviorSchema,
)

# --- Knowledge library (global, config-independent reference data used to
# populate a segment's taxonomies/modus operandi/flags/similar cases via
# "Importar de biblioteca" - snapshot-copied, never referenced live) ------


class TaxonomyLibraryEntrySchema(BaseModel):
    id: str
    code: str
    name: str
    description: str
    variables: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateTaxonomyLibraryEntryRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    variables: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class UpdateTaxonomyLibraryEntryRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    variables: list[str] | None = None
    examples: list[str] | None = None
    active: bool | None = None


# --- Channel library (global, config-independent - replaces the old fixed
# SegmentCode enum; a configuration's segments dict keys off these ids) ---


class ChannelLibraryEntrySchema(BaseModel):
    id: str
    code: str
    name: str
    description: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateChannelLibraryEntryRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UpdateChannelLibraryEntryRequest(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    active: bool | None = None


class ModusOperandiPlaybookSchema(BaseModel):
    strategy: str = Field(default="", max_length=4000)
    resolution: ShortageBehaviorSchema = Field(
        default_factory=lambda: ShortageBehaviorSchema(
            resolution_tag=ResolutionTag.SCALE_TO_ANALYST
        )
    )
    if_no_voicebot: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )
    if_no_analyst: ShortageBehaviorSchema = Field(
        default_factory=ShortageBehaviorSchema
    )


class ModusOperandiLibraryEntrySchema(BaseModel):
    id: str
    title: str
    narrative: str
    taxonomy_library_id: str
    evolved_variables: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime
    playbook: ModusOperandiPlaybookSchema | None = None


class CreateModusOperandiLibraryEntryRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    narrative: str = Field(..., min_length=1, max_length=2000)
    taxonomy_library_id: str
    evolved_variables: list[str] = Field(default_factory=list)


class UpdateModusOperandiLibraryEntryRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    narrative: str | None = Field(default=None, min_length=1, max_length=2000)
    taxonomy_library_id: str | None = None
    evolved_variables: list[str] | None = None
    active: bool | None = None
    playbook: ModusOperandiPlaybookSchema | None = None


class FlagLibraryEntrySchema(BaseModel):
    id: str
    flag_type: FlagType
    name: str
    description: str
    evolved_variables: list[str] = Field(default_factory=list)
    modus_operandi_library_ids: list[str] = Field(default_factory=list)
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateFlagLibraryEntryRequest(BaseModel):
    flag_type: FlagType
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    evolved_variables: list[str] = Field(default_factory=list)
    modus_operandi_library_ids: list[str] = Field(default_factory=list)


class UpdateFlagLibraryEntryRequest(BaseModel):
    flag_type: FlagType | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    evolved_variables: list[str] | None = None
    modus_operandi_library_ids: list[str] | None = None
    active: bool | None = None


class SimilarCaseLibraryEntrySchema(BaseModel):
    id: str
    text: str
    modus_operandi_library_id: str
    taxonomy_library_id: str
    active: bool
    created_at: datetime
    updated_at: datetime


class CreateSimilarCaseLibraryEntryRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    modus_operandi_library_id: str
    taxonomy_library_id: str


class UpdateSimilarCaseLibraryEntryRequest(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    modus_operandi_library_id: str | None = None
    taxonomy_library_id: str | None = None
    active: bool | None = None
