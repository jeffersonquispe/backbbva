from __future__ import annotations

from typing import Any, Protocol


class ModelScoringPort(Protocol):
    """Remote model-serving contract used by alert workflows."""

    def score_alert(
        self, alert_id: str, model_id: str | None = None
    ) -> dict[str, Any]: ...
