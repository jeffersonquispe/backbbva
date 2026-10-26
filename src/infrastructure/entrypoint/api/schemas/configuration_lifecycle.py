from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.infrastructure.entrypoint.api.schemas.configuration_settings import (
    GeneralSettingsSchema,
    InfraSettingsSchema,
    SegmentSettingsSchema,
    TestSettingsSchema,
)


class CreateConfigurationRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    configuration_id: str | None = None
    based_on_version: int | None = None
    parent_ref: dict[str, str | int] | None = None
    description: str = ""
    general: GeneralSettingsSchema = Field(default_factory=GeneralSettingsSchema)
    infra: InfraSettingsSchema = Field(default_factory=InfraSettingsSchema)
    test: TestSettingsSchema = Field(default_factory=TestSettingsSchema)
    created_by: str | None = Field(default=None, max_length=120)
    segments: dict[str, SegmentSettingsSchema] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_rubrics_sum_to_100(self):
        errors = [
            f"segment {code!r}, rubric {rubric.name or rubric.id!r}: "
            f"condition points sum to {total:g}, must be exactly 100"
            for code, segment in self.segments.items()
            for rubric in segment.agent.rubrics
            if not math.isclose(total := sum(condition.score for condition in rubric.conditions), 100)
        ]
        if errors:
            raise ValueError("; ".join(errors))
        return self


class ConfigurationChangeResponse(BaseModel):
    path: str
    previous: Any
    proposed: Any


class TestConfigurationResponse(BaseModel):
    valid: bool
    changes: list[ConfigurationChangeResponse]
    warnings: list[str]


class CreateConfigurationDeployRequest(BaseModel):
    target_configuration_id: str = Field(min_length=1)
    target_version: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)


class ConfigurationDeployRequestResponse(BaseModel):
    id: str
    target_configuration_id: str
    target_version: int
    current_configuration_id: str | None
    current_version: int | None
    title: str
    message: str
    changes: list[ConfigurationChangeResponse]
    requested_by: str
    requested_at: datetime
    status: str
    approved_by: str | None = None
    approved_at: datetime | None = None


class ConfigurationDeployRequestPreviewResponse(BaseModel):
    target_configuration_id: str
    target_version: int
    current_configuration_id: str | None
    current_version: int | None
    changes: list[ConfigurationChangeResponse]


class ConfigurationSummaryResponse(BaseModel):
    configuration_id: str
    version: int
    name: str
    description: str
    active: bool
    ever_activated: bool
    ever_tested: bool = False
    created_at: datetime
    updated_at: datetime
    parent_ref: dict[str, str | int] | None = None


class ConfigurationGraphNodeResponse(ConfigurationSummaryResponse):
    promotion_comment: str | None = None


class ConfigurationDetailResponse(ConfigurationSummaryResponse):
    general: GeneralSettingsSchema
    infra: InfraSettingsSchema
    test: TestSettingsSchema
    segments: dict[str, SegmentSettingsSchema] = Field(default_factory=dict)
    created_by: str | None = None
    schema_version_at_creation: int | None = None
