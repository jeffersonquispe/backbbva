from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentVerification:
    verification_id: str
    subject_id: str
    verifier: str
    status: str
    safe_metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    created_at: datetime | None = None


class AgentVerificationRepository(Protocol):
    def create(self, verification: AgentVerification) -> AgentVerification: ...

    def list_for_subject(self, subject_id: str) -> list[AgentVerification]: ...
