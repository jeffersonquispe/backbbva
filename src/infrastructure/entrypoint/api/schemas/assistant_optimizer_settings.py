from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from typing import Any, get_type_hints

from pydantic import BaseModel, ConfigDict, create_model

from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettings,
)

_NON_PERSISTED_FIELDS = {"maturing_days", "expected_coverage_pct", "stable_months"}
_type_hints = get_type_hints(AssistantOptimizerSettings)
_settings_fields = {
    field.name: (_type_hints[field.name], ...)
    for field in fields(AssistantOptimizerSettings)
    if field.name not in _NON_PERSISTED_FIELDS
}


class _SettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


AssistantOptimizerSettingsSchema = create_model(
    "AssistantOptimizerSettingsSchema", __base__=_SettingsModel, **_settings_fields
)


class AssistantOptimizerSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settings: AssistantOptimizerSettingsSchema


class AssistantOptimizerSettingChangeSchema(BaseModel):
    path: str
    previous: Any
    new: Any


class AssistantOptimizerSettingsChangeResponse(BaseModel):
    id: str
    changed_by: str
    changed_at: datetime
    changes: list[AssistantOptimizerSettingChangeSchema]


class MatureSamplePreviewResponse(BaseModel):
    eligible_alerts: int
    estimated_sample_size: int
    counts_by_stratum: dict[str, int]
    active_triggers: list[str]


class MatureSamplerSchemaFieldOption(BaseModel):
    field: str
    type: str
    description: str


class MatureSamplerSchemaMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_field: str
    marking_date_field: str
    label_value_mapping: dict[str, str]


class MatureSamplerSchemaConfigurationResponse(BaseModel):
    target_fields: list[MatureSamplerSchemaFieldOption]
    marking_date_fields: list[MatureSamplerSchemaFieldOption]
    mapping: MatureSamplerSchemaMappingRequest
