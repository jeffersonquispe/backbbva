from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.application.ports.agent_subagent_port import AgentSubagentInput


@dataclass(frozen=True)
class AgentSpecialistExecution:
    """Safe result of executing and verifying one specialist proposal."""

    status: str
    contribution: dict[str, Any] = field(default_factory=dict)
    safe_metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


class AgentSpecialistExecutor(Protocol):
    def context(self, request: AgentSubagentInput) -> dict[str, Any]: ...

    def execute(
        self,
        request: AgentSubagentInput,
        experiment: dict[str, Any],
    ) -> AgentSpecialistExecution: ...
