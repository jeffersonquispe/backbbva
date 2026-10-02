from __future__ import annotations

import base64

from src.application.ports.fraud_label_review_import_port import (
    FraudLabelReviewImportDispatcher,
)


class UploadFraudLabelReviewImport:
    def __init__(self, dispatcher: FraudLabelReviewImportDispatcher) -> None:
        self._dispatcher = dispatcher

    def execute(self, content: bytes, reviewed_by: str) -> str:
        """Returns the task id to poll for the per-row report."""
        content_b64 = base64.b64encode(content).decode("ascii")
        return self._dispatcher.dispatch(content_b64, reviewed_by)
