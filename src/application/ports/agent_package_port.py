from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentPackage:
    package_id: str
    session_id: str
    iteration_number: int
    status: str
    content: dict[str, Any] = field(default_factory=dict)
    content_hash: str | None = None
    created_at: datetime | None = None
    sealed_at: datetime | None = None
    rev: int = 0


class AgentPackageRepository(Protocol):
    def create(self, package: AgentPackage) -> AgentPackage: ...

    def get(self, package_id: str) -> AgentPackage | None: ...

    def list_for_session(
        self, session_id: str, limit: int = 50
    ) -> list[AgentPackage]: ...

    def update(self, package: AgentPackage, expected_rev: int) -> AgentPackage: ...
