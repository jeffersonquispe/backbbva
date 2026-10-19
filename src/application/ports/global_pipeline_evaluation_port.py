from __future__ import annotations

from typing import Protocol


class GlobalPipelineEvaluationDispatcher(Protocol):
    def dispatch(self, snapshot_id: str) -> None: ...
