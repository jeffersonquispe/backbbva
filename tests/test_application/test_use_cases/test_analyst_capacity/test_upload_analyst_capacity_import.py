from __future__ import annotations

import base64

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportDispatcher,
)
from src.application.use_cases.analyst_capacity.upload_analyst_capacity_import import (
    UploadAnalystCapacityImportUseCase,
)


class RecordingAnalystCapacityImportDispatcher(AnalystCapacityImportDispatcher):
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    def dispatch(self, content_b64: str) -> str:
        self.dispatched.append(content_b64)
        return "task-123"


def test_upload_base64_encodes_content_and_dispatches() -> None:
    dispatcher = RecordingAnalystCapacityImportDispatcher()
    use_case = UploadAnalystCapacityImportUseCase(dispatcher=dispatcher)

    task_id = use_case.execute(b"raw excel bytes")

    assert task_id == "task-123"
    assert dispatcher.dispatched == [
        base64.b64encode(b"raw excel bytes").decode("ascii")
    ]
