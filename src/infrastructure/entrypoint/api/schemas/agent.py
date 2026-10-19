from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateAgentSessionRequest(BaseModel):
    mode: Literal["assistant", "optimization"]
    scope: list[Literal["library", "configuration", "vector_store", "model"]] = Field(
        default_factory=list
    )
    requested_budget: dict[str, int] = Field(default_factory=dict)


class AgentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime
    budget_limits: dict[str, int]
    prompt_versions: dict[str, dict[str, str]]
    rev: int


class AgentPackageSummaryResponse(BaseModel):
    package_id: str
    session_id: str
    iteration_number: int
    status: str
    content_hash: str | None
    created_at: datetime | None
    sealed_at: datetime | None
