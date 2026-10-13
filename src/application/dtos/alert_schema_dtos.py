from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.application.ports.alert_schema_port import AlertSchemaField


@dataclass(frozen=True)
class SaveAlertSchemaDraftInput:
    fields: list[AlertSchemaField]
    field_roles: dict[str, str]
    version: int | None = None
    based_on_version: int | None = None


@dataclass(frozen=True)
class ApproveAlertSchemaInput:
    version: int
    approver_id: str
    impact_acknowledged: bool = False


@dataclass(frozen=True)
class AlertSchemaComparison:
    added: list[dict[str, Any]] = field(default_factory=list)
    changed: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    role_reassignments: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "changed": self.changed,
            "removed": self.removed,
            "role_reassignments": self.role_reassignments,
        }


@dataclass(frozen=True)
class CreateAlertSchemaSuggestionInput:
    alert_id: str
    field: str
    location: str
    comment: str
    created_by: str
