from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from src.application.ports.async_operation_port import AsyncOperationStatus


@dataclass
class CreateAsyncOperationInput:
    operation_type: str
    payload: dict[str, Any]
    created_by: str | None = None


@dataclass
class UpdateAsyncOperationInput:
    status: AsyncOperationStatus | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class AsyncOperationOutput:
    id: UUID
    operation_type: str
    status: AsyncOperationStatus
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    dispatched_at: datetime | None
    execution_backend: str | None
    external_id: str | None
