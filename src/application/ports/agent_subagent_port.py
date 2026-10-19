from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class AgentSubagentInput:
    session_id: str
    iteration_number: int
    scope: dict[str, Any]
    hypothesis: str
    budget: dict[str, int]
    cancelled: bool = False


@dataclass(frozen=True)
class AgentSubagentOutput:
    subagent: str
    contribution: dict[str, Any] = field(default_factory=dict)
    verification_status: str = "NOT_VERIFIED"
    safe_metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


class AgentSubagent(Protocol):
    """Extensible contract for an agent specialist."""

    @property
    def name(self) -> str: ...

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput: ...
