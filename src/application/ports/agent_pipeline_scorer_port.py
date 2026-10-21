from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.application.ports.agent_experiment_component_port import (
    ResolvedAgentComponent,
)


@dataclass(frozen=True)
class AgentPipelineScore:
    predictions: list[bool]
    knowledge_evidence_asset_count: int


class AgentPipelineScorer(Protocol):
    """Apply a complete component set to each row and return binary outcomes."""

    def predict_positive(
        self,
        components: tuple[ResolvedAgentComponent, ...],
        rows: list[dict[str, Any]],
    ) -> list[bool] | AgentPipelineScore: ...
