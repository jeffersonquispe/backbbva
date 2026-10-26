from __future__ import annotations

from typing import Protocol

from src.domain.agents.release import AgentRelease, RetrospectiveValidation


class AgentReleaseRepository(Protocol):
    def create_validation(
        self, validation: RetrospectiveValidation
    ) -> RetrospectiveValidation: ...

    def get_validation(self, validation_id: str) -> RetrospectiveValidation | None: ...

    def update_validation(
        self, validation: RetrospectiveValidation, *, expected_status: str
    ) -> RetrospectiveValidation: ...

    def create_release(self, release: AgentRelease) -> AgentRelease: ...

    def get_release(self, release_id: str) -> AgentRelease | None: ...

    def list_releases(
        self, limit: int = 100, statuses: set[str] | None = None
    ) -> list[AgentRelease]: ...

    def update_release(
        self, release: AgentRelease, *, expected_version: int
    ) -> AgentRelease: ...

    def record_observation(
        self, release_id: str, observation_id: str, *, disagreement: bool
    ) -> bool: ...
