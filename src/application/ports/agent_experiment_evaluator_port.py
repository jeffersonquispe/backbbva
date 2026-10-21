from __future__ import annotations

from typing import Any, Protocol

from src.domain.agents.experiment import ComponentVersionReference
from src.domain.datasets.mature_sample_entities import DatasetSnapshot


class AgentExperimentEvaluator(Protocol):
    """Run pinned components end-to-end and return protected aggregates."""

    def evaluate(
        self,
        *,
        components: tuple[ComponentVersionReference, ...],
        baseline_components: tuple[ComponentVersionReference, ...],
        snapshot: DatasetSnapshot,
        final_rows: list[dict[str, Any]],
        objective_id: str,
        objective_version: int,
    ) -> dict[str, Any]:
        """Return aggregate-only evidence from one shared final snapshot.

        Both pipelines receive the same immutable final snapshot and rows.
        The result must include `sample` (snapshot_id, content_hash,
        partition='final'), matching `baseline_sample` and `candidate_sample`,
        the exact `evaluated_components` and
        `evaluated_baseline_components`, `global`/`baseline_global`, `segments`,
        paired `delta` confidence intervals, and bootstrap metadata in
        `uncertainty`. The application use case fails closed when evidence is
        incomplete or does not match the requested pins.
        """
        ...
