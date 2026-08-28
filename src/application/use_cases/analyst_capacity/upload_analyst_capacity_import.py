from __future__ import annotations

import base64

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportDispatcher,
)


class UploadAnalystCapacityImportUseCase:
    def __init__(self, dispatcher: AnalystCapacityImportDispatcher) -> None:
        self._dispatcher = dispatcher

    def execute(self, content: bytes) -> str:
        """Returns the task id to poll for the parsed result."""
        content_b64 = base64.b64encode(content).decode("ascii")
        return self._dispatcher.dispatch(content_b64)
