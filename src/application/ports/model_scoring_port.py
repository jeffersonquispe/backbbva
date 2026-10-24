from __future__ import annotations

from typing import Any, Protocol


class ModelScoringPort(Protocol):
    """Remote model-serving contract used by alert workflows."""

    def score_alert(
        self, alert_id: str, model_id: str | None = None
    ) -> dict[str, Any]: ...

    def score_row(self, model_id: str, row: dict[str, Any]) -> dict[str, Any]: ...

    def score_pinned_row(
        self, model_id: str, artifact_sha256: str, row: dict[str, Any]
    ) -> dict[str, Any]: ...
