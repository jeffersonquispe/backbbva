from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class WorkflowStatusUpdate:
    """One status/progress fact about a running workflow.

    `step_name is None` targets the workflow-level record; otherwise it
    targets that step's record. `step_id` is required to update a step (the
    row must already exist - created synchronously before any step runs).
    """

    workflow_execution_id: UUID
    status: str
    step_name: str | None = None
    step_id: UUID | None = None
    detail: dict[str, Any] | None = None


class WorkflowStatusReporter(ABC):
    """Decouples workflow/step status writes from the pipeline's hot path.

    `report` must never block the caller on DB I/O - implementations queue
    the update and return immediately. Only the latest update per
    (workflow_execution_id, step_name) needs to survive a burst; callers
    must not rely on every intermediate `report` call reaching the DB.
    `flush` blocks until queued updates are durably written - callers use
    it before persisting a terminal state (e.g. workflow SUCCEEDED/FAILED)
    to avoid losing the last update if the process exits right after.
    """

    @abstractmethod
    def report(self, update: WorkflowStatusUpdate) -> None: ...

    @abstractmethod
    def flush(self, timeout: float | None = None) -> None: ...

    def stop(self) -> None:
        """Release any background resources; a no-op for synchronous reporters."""
        return None
