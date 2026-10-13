from __future__ import annotations

from src.application.dtos.post_process_alert_dtos import (
    PostProcessAlertInput,
    PostProcessAlertOutput,
)
from src.application.ports.clock_port import Clock
from src.application.runtime_defaults import resolve_clock


class PostProcessAlertUseCase:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = resolve_clock(clock)

    def execute(self, input: PostProcessAlertInput) -> PostProcessAlertOutput:
        closed_at = self._clock.now()
        total_duration_seconds = (closed_at - input.workflow_started_at).total_seconds()
        return PostProcessAlertOutput(
            status="success",
            resolution_path=input.resolution_path,
            total_duration_seconds=total_duration_seconds,
            closed_at=closed_at.isoformat(),
            documentation=input.documentation,
        )
