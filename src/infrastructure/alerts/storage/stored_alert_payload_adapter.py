from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from src.application.ports.alert_payload_source_port import AlertPayloadSource
from src.application.ports.alert_port import AlertRepository
from src.application.ports.object_storage_port import ObjectStoragePort


class StoredAlertPayloadAdapter(AlertPayloadSource):
    """Resolve an Alert API id to its canonical JSON stored with the alert."""

    def __init__(
        self, alerts: AlertRepository, object_storage: ObjectStoragePort
    ) -> None:
        self._alerts = alerts
        self._storage = object_storage

    def fetch_alert(self, alert_id: UUID) -> dict[str, Any]:
        alert = self._alerts.get(alert_id)
        if alert is None or alert.raw_payload_ref is None:
            raise FileNotFoundError(f"Alert API payload not found for {alert_id}")
        payload = json.loads(self._storage.get_bytes(alert.raw_payload_ref.key))
        if not isinstance(payload, dict):
            raise ValueError("Alert API payload must be a JSON object")
        return payload
