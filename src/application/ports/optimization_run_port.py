from __future__ import annotations

from typing import Protocol

from src.domain.agents.optimization_run import (
    OptimizationRun,
    OptimizationRunStatus,
    OptimizationRunTree,
)

__all__ = [
    "OptimizationRun",
    "OptimizationRunRepository",
    "OptimizationRunStatus",
    "OptimizationRunTree",
]


class OptimizationRunRepository(Protocol):
    def get(self, run_id: str) -> OptimizationRun | None: ...

    def create_once(self, run: OptimizationRun) -> OptimizationRun:
        """Create the root node; return the existing one if it is already there."""
        ...

    def update(self, run: OptimizationRun, expected_rev: int) -> OptimizationRun: ...

    def load_tree(self, run_id: str) -> OptimizationRunTree | None:
        """The whole run (root, candidates, experiments, findings) in one read."""
        ...
