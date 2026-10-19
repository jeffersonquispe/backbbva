from __future__ import annotations

from typing import Protocol

from src.domain.agents.objective import AgentObjective


class AgentObjectiveRepository(Protocol):
    def create(self, objective: AgentObjective) -> AgentObjective: ...

    def get(self, objective_id: str, version: int) -> AgentObjective | None: ...

    def list_versions(self, objective_id: str) -> list[AgentObjective]: ...

    def get_active(self, objective_id: str) -> AgentObjective | None: ...

    def activate(
        self,
        objective: AgentObjective,
        *,
        expected_active_version: int | None,
    ) -> AgentObjective: ...
