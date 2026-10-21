from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.domain.agents.experiment import ComponentVersionReference


@dataclass(frozen=True)
class ResolvedAgentComponent:
    reference: ComponentVersionReference
    content: Any


class AgentExperimentComponentResolver(Protocol):
    def active_baseline(self) -> tuple[ComponentVersionReference, ...]: ...

    def pin(
        self, component: str, entity_id: str, version: str
    ) -> ComponentVersionReference | None: ...

    def resolve(
        self, reference: ComponentVersionReference
    ) -> ResolvedAgentComponent | None: ...
