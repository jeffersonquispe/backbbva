from __future__ import annotations

from typing import Protocol

from src.domain.agents.experiment import AgentExperiment


class AgentExperimentRepository(Protocol):
    def create(self, experiment: AgentExperiment) -> AgentExperiment: ...

    def get(self, session_id: str, experiment_id: str) -> AgentExperiment | None: ...

    def list_for_session(
        self, session_id: str, limit: int = 50
    ) -> list[AgentExperiment]: ...

    def update(
        self, experiment: AgentExperiment, *, expected_status: str
    ) -> AgentExperiment: ...
