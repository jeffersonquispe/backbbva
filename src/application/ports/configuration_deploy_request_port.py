from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class ConfigurationDeployRequest:
    id: str
    target_configuration_id: str
    target_version: int
    current_configuration_id: str | None
    current_version: int | None
    title: str
    message: str
    changes: list[dict[str, Any]]
    requested_by: str
    requested_at: datetime
    requested_by_id: str | None = None
    status: str = "pending"
    approved_by: str | None = None
    approved_by_id: str | None = None
    approved_at: datetime | None = None


class ConfigurationDeployRequestRepository(Protocol):
    def create(self, request: ConfigurationDeployRequest) -> ConfigurationDeployRequest: ...
    def list(self) -> list[ConfigurationDeployRequest]: ...
    def get(self, request_id: str) -> ConfigurationDeployRequest | None: ...
    def approve(self, request_id: str, approved_by: str, approved_at: datetime, approved_by_id: str | None = None) -> ConfigurationDeployRequest: ...
