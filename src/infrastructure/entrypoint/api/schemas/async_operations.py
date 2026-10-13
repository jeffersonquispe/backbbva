from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.ports.async_execution_inspector_port import AsyncExecutionState
from src.application.ports.async_operation_port import AsyncOperationStatus


class CreateAsyncOperationRequest(BaseModel):
    operation_type: str = Field(..., min_length=1, max_length=120)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_by: str | None = Field(default=None, max_length=120)


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


class ReconcileAsyncOperationsRequest(BaseModel):
    limit: int = Field(default=100, ge=1, le=500)


class ReconciledAsyncOperationResponse(BaseModel):
    id: UUID
    previous_status: AsyncOperationStatus
    current_status: AsyncOperationStatus
    execution_state: AsyncExecutionState
    detail: str | None


class ReconcileAsyncOperationsResponse(BaseModel):
    inspected: int
    updated: int
    operations: list[ReconciledAsyncOperationResponse]
