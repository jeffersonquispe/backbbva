from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RunAlertReviewWorkflowOutput:
    """``status`` is ``ok``, ``skipped`` or ``not_found``."""

    status: str
    workflow_execution_id: str
