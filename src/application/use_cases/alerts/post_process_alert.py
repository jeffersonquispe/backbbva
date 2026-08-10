from __future__ import annotations

from datetime import datetime, timezone

from src.application.dtos.post_process_alert_dtos import (
    PostProcessAlertInput,
    PostProcessAlertOutput,
)


class PostProcessAlertUseCase:
    def execute(self, input: PostProcessAlertInput) -> PostProcessAlertOutput:
        closed_at = datetime.now(timezone.utc)
        total_duration_seconds = (
            closed_at - input.workflow_started_at
        ).total_seconds()
        return PostProcessAlertOutput(
            status="success",
            resolution_path=input.resolution_path,
            total_duration_seconds=total_duration_seconds,
            closed_at=closed_at.isoformat(),
        )
