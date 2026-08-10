from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from src.application.dtos.post_process_alert_dtos import PostProcessAlertInput
from src.application.use_cases.alerts.post_process_alert import (
    PostProcessAlertUseCase,
)


def test_post_process_computes_duration_status_and_resolution_path() -> None:
    started_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    use_case = PostProcessAlertUseCase()

    output = use_case.execute(
        PostProcessAlertInput(
            alert_id=uuid.uuid4(),
            workflow_started_at=started_at,
            resolution_path="bidi",
        )
    )

    assert output.status == "success"
    assert output.resolution_path == "bidi"
    assert output.total_duration_seconds >= 5
    assert datetime.fromisoformat(output.closed_at) > started_at
