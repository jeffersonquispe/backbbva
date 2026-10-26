from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from src.domain.agents.experiment import ComponentVersionReference
from src.domain.agents.objective import AgentObjective


@dataclass(frozen=True)
class AgentSubagentInput:
    session_id: str
    iteration_number: int
    scope: dict[str, Any]
    hypothesis: str
    budget: dict[str, int]
    prompt_versions: dict[str, dict[str, str]] = field(default_factory=dict)
    objective_id: str | None = None
    objective_version: int | None = None
    objective: AgentObjective | None = None
    baseline_components: tuple[ComponentVersionReference, ...] = ()
    # Curated optimizer levers loaded from the project graph, keyed by specialist.
    project_map: dict[str, dict[str, str]] = field(default_factory=dict)
    cancelled: bool = False


@dataclass(frozen=True)
class AgentSubagentOutput:
    subagent: str
    contribution: dict[str, Any] = field(default_factory=dict)
    verification_status: str = "NOT_VERIFIED"
    safe_metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    experiment_candidate_components: tuple[ComponentVersionReference, ...] = ()


class AgentSubagent(Protocol):
    """Extensible contract for an agent specialist."""

    @property
    def name(self) -> str: ...

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput: ...
