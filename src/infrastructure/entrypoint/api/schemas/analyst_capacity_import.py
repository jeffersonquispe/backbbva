from __future__ import annotations

from pydantic import BaseModel, Field

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportStatus,
)

# --- Analyst capacity import --------------------------------------------
# Excel import for OperationalSettings.analyst_capacity -
# result only feeds the frontend's form until the admin saves it,
# see analyst_capacity_import_port.py.


class AnalystCapacityImportProfileSchema(BaseModel):
    id: str
    name: str
    description: str = ""
    hourly: list[int]


class UploadAnalystCapacityImportResponse(BaseModel):
    task_id: str
    status: AnalystCapacityImportStatus


class AnalystCapacityImportResponse(BaseModel):
    task_id: str
    status: AnalystCapacityImportStatus
    profiles: list[AnalystCapacityImportProfileSchema] = Field(default_factory=list)
    day_overrides: dict[int, str] = Field(default_factory=dict)
    error: str | None = None
