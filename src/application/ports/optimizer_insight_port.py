from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.domain.agents.finding import (
    OptimizerInsight,
    OptimizerInsightKind,
    OptimizerInsightStatus,
)

__all__ = [
    "OptimizerInsight",
    "OptimizerInsightKind",
    "OptimizerInsightRepository",
    "OptimizerInsightStatus",
]


class OptimizerInsightRepository(Protocol):
    def create(self, insight: OptimizerInsight) -> OptimizerInsight: ...

    def get(self, insight_id: str) -> OptimizerInsight | None: ...

    def update(
        self, insight: OptimizerInsight, expected_rev: int
    ) -> OptimizerInsight: ...

    def list_by_scope(
        self, scope_key: str, status: OptimizerInsightStatus, limit: int = 50
    ) -> list[OptimizerInsight]: ...

    def list_due_for_review(
        self, before: datetime, limit: int = 50
    ) -> list[OptimizerInsight]:
        """SUPPORTED insights whose `review_after` has passed."""
        ...
