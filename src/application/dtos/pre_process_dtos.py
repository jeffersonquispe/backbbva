from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class PreProcessAlertInput:
    alert_id: UUID
    payload: dict[str, Any]
    schema: Any | None = None


@dataclass
class PreProcessAlertOutput:
    schema_version: int = 0
    input: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    roles: dict[str, Any] = field(default_factory=dict)
    enrichment: dict[str, Any] = field(default_factory=dict)
    pre_process_note: str = ""
    # Transitional deserialization fields for old persisted workflow steps.
    mandatory_fields: dict[str, Any] = field(default_factory=dict)
    optional_fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.input:
            self.input = {**self.mandatory_fields, **self.optional_fields}
        if not self.roles:
            self.roles = {
                role: self.input[role]
                for role in (
                    "event_id", "event_time", "event_type", "channel",
                    "entrypoint", "amount", "customer_id", "account_id",
                    "session_id",
                )
                if role in self.input
            }
