from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.ports.async_operation_port import AsyncOperationStatus


class UpdateAsyncOperationRequest(BaseModel):
    status: AsyncOperationStatus | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class AsyncOperationResponse(BaseModel):
    id: UUID
    operation_type: str
    status: AsyncOperationStatus
    schema_version: int | None = None
    configuration_ref: dict[str, Any] | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, Any] = Field(default_factory=dict)
    history_prev_alerta: list[dict[str, Any]] = Field(default_factory=list)
    agent_output: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    dispatched_at: datetime | None
    execution_backend: str | None
    external_id: str | None


class AsyncOperationPollingResponse(BaseModel):
    id: UUID
    status: AsyncOperationStatus
    done: bool
    retry_after_seconds: int | None
    result: dict[str, Any] | None
    error: str | None
    updated_at: datetime
