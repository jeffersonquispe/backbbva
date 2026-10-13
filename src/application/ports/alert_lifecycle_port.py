"""What the platform already stored about one alert's life, read back for
the metrics backfill (R6): which events happened, with their real
timestamps. Only stored facts - a value that was never persisted (e.g. the
segment, which today lives only in the workflow's in-memory context) is
None here, and the backfill turns it into "unknown"/"pending", never a
guess."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from src.domain.alerts.entities import (
    AlertRecord,
)


@dataclass(frozen=True)
class WorkflowOutcomeFacts:
    """The alert's review workflow, once it reached a terminal state."""

    # WorkflowStatus value: "SUCCEEDED" or "FAILED".
    status: str
    finished_at: datetime
    # workflow.output["status"]: "discarded" (deterministic rule), "skipped"
    # (agent off) or post_process's status; None when the run failed.
    output_status: str | None = None
    # The executor step's executed_action ("none", "block", "bidi",
    # "voicebot", "scale_to_analyst"); None when it never ran.
    executed_action: str | None = None


@dataclass(frozen=True)
class HumanResolutionFacts:
    """An analyst resolution (decision) or a voicebot callback (outcome),
    from the reservation audit trail."""

    occurred_at: datetime
    decision: str | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class AlertLifecycleFacts:
    origin: str | None = None
    # Only when the run pinned one (configuration_ref); the configuration
    # resolved at pre_process time is not persisted.
    configuration_id: str | None = None
    workflow: WorkflowOutcomeFacts | None = None
    analyst_resolution: HumanResolutionFacts | None = None
    voicebot_callback: HumanResolutionFacts | None = None


class AlertLifecycleReader(ABC):
    @abstractmethod
    def read(self, alert: AlertRecord) -> AlertLifecycleFacts:
        """The stored facts for this alert (an empty AlertLifecycleFacts
        when nothing beyond the alert itself was stored)."""
        raise NotImplementedError
