from __future__ import annotations

import json
from typing import Any

from src.application.ports.object_storage_port import ObjectStoragePort
from src.domain.alerts.entities import (
    AlertRecord,
)


class RawAlertPayloadLoader:
    """The single boundary for raw alert payloads."""

    def __init__(self, object_storage: ObjectStoragePort) -> None:
        self._storage = object_storage

    def store(self, alert_id: str, payload: dict[str, Any]):
        return self._storage.put_text(
            f"alerts/{alert_id}/raw-payload.json",
            json.dumps(payload, ensure_ascii=False, default=str),
            "application/json",
        )

    def load(self, alert: AlertRecord) -> dict[str, Any]:
        if alert.raw_payload_ref is None:
            raise ValueError("Alert has no raw payload reference")
        return json.loads(self._storage.get_bytes(alert.raw_payload_ref.key))
