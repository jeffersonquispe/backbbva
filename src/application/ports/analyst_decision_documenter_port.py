from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class DocumentationDispatchRef:
    backend: str
    external_id: str | None = None


class AnalystDecisionDocumenter(ABC):
    """Fire-and-forget dispatch: hands the pipeline's step data off to run
    concurrently with the workflow, rather than blocking it. `steps` is the
    already-computed per-step output data (pre_process, profiling,
    classification, adversarial, analyst), passed by value so the
    documentation job never races the pipeline's own DynamoDB writes."""

    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        steps: dict[str, dict[str, Any]],
    ) -> DocumentationDispatchRef:
        raise NotImplementedError
