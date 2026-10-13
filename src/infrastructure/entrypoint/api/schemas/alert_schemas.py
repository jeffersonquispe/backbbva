from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaFieldType,
    AlertSchemaStatus,
)


class AlertSchemaFieldSchema(BaseModel):
    id: str
    data_source: AlertSchemaDataSource
    field: str
    field_name: str = ""
    field_ds_loc: str = ""
    type: AlertSchemaFieldType = AlertSchemaFieldType.STRING
    is_alert: bool = True
    is_mandatory: bool = False
    is_history: bool = False
    is_core: bool = False
    is_label: bool = False
    is_sensible: bool = False
    sensitivity_strategy: str | None = None
    group: str = ""
    description: str = ""
    use_locale: bool = False
    locale_type: str | None = None


class CreateAlertSchemaDraft(BaseModel):
    version: int | None = Field(default=None, ge=1)
    fields: list[AlertSchemaFieldSchema] = Field(default_factory=list)
    field_roles: dict[str, str] = Field(default_factory=dict)
    based_on_version: int | None = Field(default=None, ge=1)


class AlertSchemaVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    version: int
    status: AlertSchemaStatus
    fields: list[AlertSchemaFieldSchema]
    field_roles: dict[str, str]
    proposed_by: str | None
    proposed_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    impact_acknowledged: bool
    based_on_version: int | None
    comparison: dict[str, Any] = Field(default_factory=dict)
    impact: list[dict[str, Any]] = Field(default_factory=list)


class ApproveAlertSchemaRequest(BaseModel):
    impact_acknowledged: bool = False


class CreateAlertSchemaSuggestionRequest(BaseModel):
    alert_id: str
    field: str
    location: str
    comment: str


class AlertSchemaSuggestionResponse(BaseModel):
    id: str
    alert_id: str
    field: str
    location: str
    comment: str
    created_by: str
    created_at: datetime


class AlertSchemaPresenceFieldResponse(BaseModel):
    field_id: str
    field: str
    location: str
    present_count: int
    last_seen: datetime | None
    trend: dict[str, Any]
    example: str | None
    distribution: dict[str, Any] | None


class AlertSchemaUnknownLocationResponse(BaseModel):
    location: str
    frequency: int


class AlertSchemaPresenceResponse(BaseModel):
    report_day: date
    generated_at: datetime
    schema_version: int
    alert_count: int
    fields: list[AlertSchemaPresenceFieldResponse]
    unknown_locations: list[AlertSchemaUnknownLocationResponse]
