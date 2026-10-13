from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol


class AlertSchemaStatus(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACTIVE = "active"
    HISTORICAL = "historical"
    REJECTED = "rejected"


class AlertSchemaFieldType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    BOOL = "bool"
    DATE = "date"
    DATETIME = "datetime"
    LIST = "list"


class AlertSchemaDataSource(StrEnum):
    ARIC = "aric"
    HOST = "host"
    ARIA = "aria"


class AlertSchemaValidationError(ValueError):
    pass


SYSTEM_ROLES: dict[str, AlertSchemaFieldType] = {
    "event_id": AlertSchemaFieldType.STRING,
    "event_time": AlertSchemaFieldType.DATETIME,
    "event_type": AlertSchemaFieldType.STRING,
    "channel": AlertSchemaFieldType.STRING,
    "entrypoint": AlertSchemaFieldType.STRING,
    "amount": AlertSchemaFieldType.NUMBER,
    "customer_id": AlertSchemaFieldType.STRING,
    "account_id": AlertSchemaFieldType.STRING,
    "session_id": AlertSchemaFieldType.STRING,
}

REQUIRED_SYSTEM_ROLES = frozenset(
    {
        "event_id",
        "event_time",
        "event_type",
        "channel",
        "entrypoint",
        "amount",
        "customer_id",
    }
)


@dataclass(frozen=True)
class AlertSchemaField:
    id: str
    data_source: AlertSchemaDataSource
    field: str
    field_name: str = ""
    field_ds_loc: str = ""
    type: AlertSchemaFieldType = AlertSchemaFieldType.STRING
    is_alert: bool = True
    is_mandatory: bool = False
    is_history: bool = False
    is_core: bool = False
    is_label: bool = False
    is_sensible: bool = False
    sensitivity_strategy: str | None = None
    group: str = ""
    description: str = ""
    use_locale: bool = False
    locale_type: str | None = None


@dataclass(frozen=True)
class AlertSchemaVersion:
    version: int
    status: AlertSchemaStatus = AlertSchemaStatus.DRAFT
    fields: list[AlertSchemaField] = field(default_factory=list)
    field_roles: dict[str, str] = field(default_factory=dict)
    proposed_by: str | None = None
    proposed_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    impact_acknowledged: bool = False
    based_on_version: int | None = None
    comparison: dict[str, object] = field(default_factory=dict)
    impact: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class AlertSchemaSuggestion:
    id: str
    alert_id: str
    field: str
    location: str
    comment: str
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class AlertSchemaPresenceField:
    field_id: str
    field: str
    location: str
    present_count: int
    last_seen: datetime | None = None
    trend: dict[str, object] = field(default_factory=dict)
    example: str | None = None
    distribution: dict[str, object] | None = None


@dataclass(frozen=True)
class AlertSchemaUnknownLocation:
    location: str
    frequency: int


@dataclass(frozen=True)
class AlertSchemaPresenceReport:
    report_day: date
    generated_at: datetime
    schema_version: int
    alert_count: int
    fields: list[AlertSchemaPresenceField] = field(default_factory=list)
    unknown_locations: list[AlertSchemaUnknownLocation] = field(default_factory=list)


class AlertSchemaPresenceReportRepository(Protocol):
    def save(self, report: AlertSchemaPresenceReport) -> AlertSchemaPresenceReport: ...
    def get(self, report_day: date) -> AlertSchemaPresenceReport | None: ...
    def get_latest(self) -> AlertSchemaPresenceReport | None: ...
    def list_before(
        self, report_day: date, limit: int = 30
    ) -> list[AlertSchemaPresenceReport]: ...


class AlertSchemaSuggestionRepository(Protocol):
    def create(self, suggestion: AlertSchemaSuggestion) -> AlertSchemaSuggestion: ...
    def get(self, suggestion_id: str) -> AlertSchemaSuggestion | None: ...
    def update(self, suggestion: AlertSchemaSuggestion) -> AlertSchemaSuggestion: ...
    def list(self) -> list[AlertSchemaSuggestion]: ...


def validate_schema(version: AlertSchemaVersion) -> None:
    fields_by_id = {item.id: item for item in version.fields}
    if len(fields_by_id) != len(version.fields):
        raise AlertSchemaValidationError("Field ids must be unique")

    locations: set[tuple[AlertSchemaDataSource, str]] = set()
    for item in version.fields:
        location = (item.data_source, item.field_ds_loc)
        if item.field_ds_loc and location in locations:
            raise AlertSchemaValidationError(
                "field_ds_loc must be unique within each data_source"
            )
        if item.field_ds_loc:
            locations.add(location)
        if item.is_core and not item.field_name:
            raise AlertSchemaValidationError("Core fields require field_name")
        if item.is_label and item.is_history:
            raise AlertSchemaValidationError("A label cannot be a history field")
        if item.is_sensible and item.sensitivity_strategy not in {
            "anonymize",
            "obfuscate",
        }:
            raise AlertSchemaValidationError(
                "Sensitive fields require a valid strategy"
            )
        if item.use_locale and not item.locale_type:
            raise AlertSchemaValidationError("Localized fields require locale_type")
        if item.data_source == AlertSchemaDataSource.ARIA and item.is_mandatory:
            raise AlertSchemaValidationError("ARIA fields cannot be mandatory")

    if not version.fields and not version.field_roles:
        return

    for role in SYSTEM_ROLES:
        if role not in REQUIRED_SYSTEM_ROLES and role not in version.field_roles:
            continue
        expected_type = SYSTEM_ROLES[role]
        field_id = version.field_roles.get(role)
        if field_id is None:
            raise AlertSchemaValidationError(f"Missing required role: {role}")
        selected = fields_by_id.get(field_id)
        if selected is None:
            raise AlertSchemaValidationError(f"Role {role} references an unknown field")
        if not selected.is_alert or selected.is_label or selected.type != expected_type:
            raise AlertSchemaValidationError(
                f"Role {role} references an incompatible field"
            )


class AlertSchemaRepository(Protocol):
    def get_active(self) -> AlertSchemaVersion | None: ...
    def list_versions(self) -> list[AlertSchemaVersion]: ...
    def get(self, version: int) -> AlertSchemaVersion | None: ...
    def save_draft(self, schema: AlertSchemaVersion) -> AlertSchemaVersion: ...
    def update(self, schema: AlertSchemaVersion) -> AlertSchemaVersion: ...
