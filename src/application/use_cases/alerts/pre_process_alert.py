from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar
from uuid import UUID

from src.application.dtos.pre_process_dtos import (
    PreProcessAlertInput,
    PreProcessAlertOutput,
)
from src.application.ports.alert_payload_source_port import AlertPayloadSource
from src.application.ports.alert_schema_port import (
    AlertSchemaDataSource,
    AlertSchemaField,
    AlertSchemaFieldType,
    AlertSchemaRepository,
    AlertSchemaVersion,
)
from src.application.ports.aric_alert_port import AricAlertPort, AricAlertSignals
from src.application.ports.host_service_customer_port import (
    HostServiceCustomerProfilePort,
)
from src.application.ports.host_service_personal_data_changes_port import (
    HostServicePersonalDataChangesPort,
)
from src.application.ports.host_service_transaction_history_port import (
    HostServiceTransactionHistoryPort,
    TransactionHistoryEntry,
)
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.domain.alerts.entities import AlertOrigin
from src.domain.alerts.exceptions import (
    AlertFieldTypeMismatchError,
    MandatoryAlertDataMissingError,
    NoActiveAlertSchemaError,
)
from src.domain.datasets.mature_sample_entities import (
    OPTIMIZER_REPLAY_HISTORY_COLUMN,
)
from src.domain.workflows.entities import (
    WorkflowStepStatus,
)

MAX_FETCH_ATTEMPTS = 3

# Schema-driven extraction. Dotted paths are owned by AlertSchemaField rows;
# this module intentionally has no field catalogue.
"""
# Dotted-path candidates per mandatory data point (tried in order, first
# non-empty wins). Paths that traverse a list take its first element -
# good enough for the single-alert-object case this covers today; alerts
# carrying multiple entities/models per event need real per-item merging,
# deferred until that shape shows up.
#
# Two schemas are live candidates per field: the original raw ARIC
# event shape (dotted/camelCase, e.g. "amount.baseValue") and
# Muestra_total_ARIA.csv's flat analytics-export shape (snake_case, e.g.
# "amount_value") - the latter is the reference/standard dataset now, so
# every field it actually carries has priority-ordered aliases here
# rather than a separate translation layer. Fields that schema simply
# doesn't have (no session id, no merchant info, no entry mode, ...) were
# demoted to _OPTIONAL_FIELD_PATHS below - captured when present, never
# block pre_process when absent.
_LEGACY_MANDATORY_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "rules": ("object.triggeredRules", "triggered_rules"),
    "event_time": ("eventTime", "fecha_transaccion"),
    "event_type": ("eventType", "eventtype"),
    "customer_id": ("customerId", "customerid"),
    "channel": ("channel",),
    "integration_point": ("integrationPoint", "integrationpoint"),
    "ip_channel": ("device.ipAddress", "device_ipaddress_encrypted"),
    "client_code": ("customerClientCode", "personalId", "numero_documento"),
    "event_id": ("eventId", "eventid"),
}

# Card-only data points: mandatory, but only for card transactions.
_LEGACY_CARD_ONLY_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "card_bin": ("cardBIN",),
    "authorization_phase": ("authorizationPhase",),
}

# Present in the spec but flagged "no se usa", plus the raw-ARIC-only
# fields the reference dataset doesn't carry at all (tags, triggered
# models, account/merchant/session id, entry mode, description,
# response, direction, biocatch IP, user agent) - captured when
# available, never blocks pre_process. device_id also lives here despite
# being a real field in the reference schema: 44% of its rows have no
# deviceid at all (checked directly against Muestra_total_ARIA.csv) - a
# structural absence for non-digital channels, not sporadic missing
# data, so it doesn't belong with fields whose absence should escalate.
_LEGACY_OPTIONAL_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "reason_code": ("msgReason",),
    "biocatch_score": ("biocatch.score", "biocatch_score"),
    "model_score": ("model.score", "Model_score", "model_score"),
    "counterparty": (
        "counterpartyName.fullName",
        "counterpartyId",
        "counterpartyentityid_encrypted",
    ),
    "amount": ("amount.baseValue", "amount_value"),
    "transaction_id": ("transactionId", "transactionid"),
    "biocatch_muid": ("biocatch.muid",),
    "tags": ("object.tags",),
    "triggered_models": ("object.triggeredModels",),
    "account_id": ("accountId",),
    "device_id": ("_metadata.searchable.deviceId", "deviceid"),
    "entry_mode": (
        "entryMode.terminalDataInputModeCapability",
        "entryMode.dataInputMode",
    ),
    "merchant_id": ("merchantId",),
    "merchant_name": ("merchantName",),
    "session_id": ("session.sessionId", "biocatch.customerSessionID"),
    "description": ("serviceDescription",),
    "response": ("msgStatus",),
    "direction": ("direction",),
    "ip_biocatch": ("biocatch.ip",),
    "user_agent": ("device.userAgentString",),
    "max_amount_pse": ("MontoMasAltoPSE",),
    "max_amount_payment_gateway": ("MontoMasAltoPasarelaPago",),
    "max_amount_breb": ("MontoMasAltoBreB",),
    "max_amount_glomo": ("MontoMasAltoGlomo",),
    "max_amount_net": ("MontoMasAltoNet",),
    "max_amount_loan": ("MontoMasAltoPrestamo",),
    "max_amount_bills": ("MontoMasAltoFacturas",),
    "max_amount_card_withdrawals": ("MontoMasAltoRetirosTarjeta",),
}

# These export columns describe a review outcome or a matured fraud label.
# Keeping them out of mandatory_fields/optional_fields prevents target leakage
# into profiling and classification. The raw payload remains persisted for
# test-run evaluation (marcacion_final and tipo are threaded separately by the
# workflow).
_LEGACY_OUTCOME_ONLY_FIELDS = frozenset(
    {
        "reviewstatus_first",
        "marcacion_final",
        "razon_marcacion",
        "fecha_primer_marcacion",
        "fecha_ultima_marcacion",
        "output_tags",
        "tipo",
    }
)

_LEGACY_PAYLOAD_ARIC_SIGNAL_PATHS: dict[str, tuple[str, ...]] = {
    "is_mobile_rat": ("biocatch.isMobileRat", "biocatch_isMobileRat"),
    "is_emulator_rat": ("biocatch.isEmulator", "biocatch_isEmulator"),
    "is_rat": ("biocatch.isRat", "biocatch_isRat"),
    "is_bot": ("biocatch.isBot", "biocatch_isBot"),
    "ind_robo1": ("biocatch.indrobo1", "biocatch_indrobo1"),
    "is_on_call_active": ("biocatch.isOnCall", "biocatch_isOnCall"),
    "is_voip_on_call": ("biocatch.isVoipOnCall", "biocatch_isVoipOnCall"),
    "screen_broadcast": (
        "biocatch.screenBroadcast",
        "biocatch_screenBroadcast",
    ),
}
"""

T = TypeVar("T")


def _get_path(data: Any, path: str) -> Any:
    value = data
    for key in path.split("."):
        if isinstance(value, list):
            value = value[0] if value else None
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _first_present(payload: dict[str, Any], paths: tuple[str, ...]) -> Any:
    for path in paths:
        value = _get_path(payload, path)
        if value not in (None, "", []):
            return value
    return None


def _to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "si", "sí"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _extract_value(source: Any, location: str) -> Any:
    value = source
    for part in location.split(".") if location else ():
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None:
            return None
        value = (
            value.get(part) if isinstance(value, dict) else getattr(value, part, None)
        )
    return value


def _present(value: Any) -> bool:
    return value not in (None, "", [])


def _valid_type(value: Any, expected: AlertSchemaFieldType) -> bool:
    if expected == AlertSchemaFieldType.STRING:
        return isinstance(value, str)
    if expected == AlertSchemaFieldType.NUMBER:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == AlertSchemaFieldType.BOOL:
        return isinstance(value, bool)
    if expected in {AlertSchemaFieldType.DATE, AlertSchemaFieldType.DATETIME}:
        return isinstance(value, (str, datetime))
    return expected == AlertSchemaFieldType.LIST and isinstance(value, list)


def _coerce_schema_value(value: Any, expected: AlertSchemaFieldType) -> Any:
    """Normalize scalar values read from CSV-backed datasets."""
    if expected == AlertSchemaFieldType.NUMBER and isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return value
    return value


def _extract_fields(
    fields: list[AlertSchemaField], sources: dict[AlertSchemaDataSource, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    values: dict[str, Any] = {}
    by_id: dict[str, Any] = {}
    missing: list[str] = []
    selected_fields: set[str] = set()
    for field in fields:
        if field.field in selected_fields:
            continue
        source = sources.get(field.data_source)
        value = _extract_value(source, field.field_ds_loc)
        if not _present(value):
            continue
        value = _coerce_schema_value(value, field.type)
        if not _valid_type(value, field.type):
            raise AlertFieldTypeMismatchError(field.field, field.type.value, value)
        selected_fields.add(field.field)
        for candidate in fields:
            if candidate.field == field.field:
                by_id[candidate.id] = value
        values[field.field] = value
    mandatory_names = {field.field for field in fields if field.is_mandatory}
    missing.extend(name for name in mandatory_names if name not in values)
    return values, by_id, missing


def _schema_values(
    schema: AlertSchemaVersion, sources: dict[AlertSchemaDataSource, Any]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str]]:
    input_fields = [
        f for f in schema.fields if f.is_alert and not f.is_label and not f.is_history
    ]
    label_fields = [f for f in schema.fields if f.is_label]
    input_values, by_id, missing = _extract_fields(input_fields, sources)
    labels, _, _ = _extract_fields(label_fields, sources)
    for role, field_id in schema.field_roles.items():
        if field_id not in by_id:
            missing.append(role)
    roles = {
        role: by_id[field_id]
        for role, field_id in schema.field_roles.items()
        if field_id in by_id
    }
    return input_values, labels, roles, sorted(set(missing))


def _history_values(
    schema: AlertSchemaVersion, entries: list[TransactionHistoryEntry]
) -> list[dict[str, Any]]:
    history_fields = [f for f in schema.fields if f.is_history and not f.is_label]
    result: list[dict[str, Any]] = []
    for entry in entries:
        source = dataclasses.asdict(entry)
        additional = source.pop("additional_fields", {})
        if isinstance(additional, dict):
            source = {**additional, **source}
        values, _, _ = _extract_fields(
            history_fields,
            {
                AlertSchemaDataSource.ARIC: source,
                AlertSchemaDataSource.HOST: source,
            },
        )
        result.append(values)
    return result


def _optimizer_replay_history(
    schema: AlertSchemaVersion, payload: dict[str, Any]
) -> tuple[list[TransactionHistoryEntry], list[dict[str, Any]]] | None:
    raw = payload.get(OPTIMIZER_REPLAY_HISTORY_COLUMN)
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("OPTIMIZER_REPLAY_HISTORY_INVALID") from error
    if not isinstance(raw, list):
        raise ValueError("OPTIMIZER_REPLAY_HISTORY_INVALID")
    fields = [
        field for field in schema.fields if field.is_history and not field.is_label
    ]
    sources = {field.data_source for field in fields}
    entries: list[TransactionHistoryEntry] = []
    mapped_history: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError("OPTIMIZER_REPLAY_HISTORY_INVALID")
        values, _, missing = _extract_fields(
            fields, {source: item for source in sources}
        )
        if missing:
            raise ValueError("OPTIMIZER_REPLAY_HISTORY_INVALID")
        mapped_history.append(values)
        amount = values.get("amount")
        entries.append(
            TransactionHistoryEntry(
                event_id=str(values.get("event_id") or f"optimizer-history-{index}"),
                event_type=str(values.get("event_type") or "unknown"),
                event_time=str(values.get("event_time") or ""),
                amount=(
                    float(amount)
                    if isinstance(amount, (int, float)) and not isinstance(amount, bool)
                    else None
                ),
                status=_optional_history_text(values.get("status")),
                alerts=_optional_history_text(values.get("alerts")),
                account_id=_optional_history_text(values.get("account_id")),
                integration_point=_optional_history_text(
                    values.get("integration_point")
                ),
                channel=_optional_history_text(values.get("channel")),
                counterparty=_optional_history_text(values.get("counterparty")),
                additional_fields=values,
            )
        )
    return entries, mapped_history


def _optional_history_text(value: Any) -> str | None:
    return str(value) if value is not None else None


# Canonical schema field names of the BioCatch flags an alert carries itself.
# Snapshot-only enrichment reads them from the schema-shaped input instead of
# calling ARIC, so a replay sees the flags the alert had at decision time.
_ALERT_ARIC_SIGNAL_FIELDS: dict[str, str] = {
    "is_mobile_rat": "biocatch_isMobileRat",
    "is_emulator_rat": "biocatch_isEmulator",
    "is_rat": "biocatch_isRat",
    "is_bot": "biocatch_isBot",
    "ind_robo1": "biocatch_indrobo1",
    "is_on_call_active": "biocatch_isOnCall",
    "is_voip_on_call": "biocatch_isVoipOnCall",
    "screen_broadcast": "biocatch_screenBroadcast",
}


def _alert_aric_signals(values: dict[str, Any]) -> AricAlertSignals:
    return AricAlertSignals(
        **{
            name: _to_bool(values.get(field))
            for name, field in _ALERT_ARIC_SIGNAL_FIELDS.items()
        }
    )


def _merge_aric_signals(
    payload: dict[str, Any], fetched: AricAlertSignals
) -> AricAlertSignals:
    return fetched


def _transaction_history_from_payload(
    payload: dict[str, Any],
) -> list[TransactionHistoryEntry] | None:
    """Dataset-provided history (test-run CSVs carrying a raw
    "transacciones_json" column) takes priority over the host-service
    call - returns None (not an empty list) when absent so the caller
    knows to fall back, same signal a real production alert gives since
    it never carries this column at all."""
    raw = payload.get("transacciones_json")
    if not raw:
        return None
    try:
        entries = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None

    history: list[TransactionHistoryEntry] = []
    for i, entry in enumerate(entries):
        if isinstance(entry, str):
            try:
                entry = json.loads(entry)
            except json.JSONDecodeError:
                continue
        if not isinstance(entry, dict):
            continue
        amount = entry.get("amount_value")
        event_time = str(entry.get("eventtime") or "")
        history.append(
            TransactionHistoryEntry(
                # Source rows carry no id of their own - derived so it's
                # stable across re-runs of the same dataset row.
                event_id=hashlib.sha1(f"{event_time}-{i}".encode()).hexdigest()[:16],
                event_type=str(entry.get("tipo_transaccion") or "unknown"),
                event_time=event_time,
                amount=float(amount) if amount is not None else None,
                alerts=(
                    str(entry["alertas"]) if entry.get("alertas") is not None else None
                ),
                account_id=(
                    str(entry["cuenta_origen"])
                    if entry.get("cuenta_origen") is not None
                    else None
                ),
                integration_point=(
                    str(entry["integrationpoint"])
                    if entry.get("integrationpoint") is not None
                    else None
                ),
                channel=(
                    str(entry["canal"]) if entry.get("canal") is not None else None
                ),
                counterparty=(
                    str(entry["destino"]) if entry.get("destino") is not None else None
                ),
            )
        )
    return history


def _with_retry(fn: Callable[[], T], attempts: int = MAX_FETCH_ATTEMPTS) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - retry any transient adapter failure
            last_error = exc
            if attempt < attempts:
                time.sleep(0.05 * attempt)
    assert last_error is not None
    raise last_error


class PreProcessAlertUseCase:
    def __init__(
        self,
        aric_alert_port: AricAlertPort,
        host_customer_profile_port: HostServiceCustomerProfilePort,
        host_transaction_history_port: HostServiceTransactionHistoryPort,
        host_personal_data_changes_port: HostServicePersonalDataChangesPort,
        schema_repository: AlertSchemaRepository | None = None,
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
        alert_payload_source: AlertPayloadSource | None = None,
    ) -> None:
        self._aric = aric_alert_port
        self._host_customer = host_customer_profile_port
        self._host_tx_history = host_transaction_history_port
        self._host_data_changes = host_personal_data_changes_port
        self._schema_repository = schema_repository
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id
        self._alert_payload_source = alert_payload_source

    def _report_progress(self, detail: str) -> None:
        if self._status_reporter is None or self._workflow_execution_id is None:
            return
        self._status_reporter.report(
            WorkflowStatusUpdate(
                workflow_execution_id=self._workflow_execution_id,
                step_name="pre_process",
                step_id=self._step_id,
                status=WorkflowStepStatus.RUNNING,
                detail={"output": {"progress": detail}},
            )
        )

    def execute(self, input: PreProcessAlertInput) -> PreProcessAlertOutput:
        schema = input.schema or (
            self._schema_repository.get_active() if self._schema_repository else None
        )
        if schema is None:
            raise NoActiveAlertSchemaError()
        payload = input.payload
        if input.origin == AlertOrigin.PRODUCTION:
            payload_source = self._alert_payload_source
            if payload_source is None:
                raise RuntimeError("Production alert payload source is not configured")
            self._report_progress("fetching_alert_from_alert_api")
            payload = _with_retry(lambda: payload_source.fetch_alert(input.alert_id))
        aric_input, labels, roles, missing = _schema_values(
            schema, {AlertSchemaDataSource.ARIC: payload}
        )
        if missing:
            raise MandatoryAlertDataMissingError(missing)
        customer_id = str(roles["customer_id"])
        account_id = roles.get("account_id")
        session_id = roles.get("session_id")
        event_id = str(roles["event_id"])
        transaction_history: list[TransactionHistoryEntry] | None
        replay_history: list[dict[str, Any]] | None = None

        if input.skip_external_enrichment:
            # Optimizer replay must not call customer, ARIC, or history
            # services using identities intentionally absent from snapshots.
            aric_signals = _alert_aric_signals(aric_input)
            customer_profile = payload.get("customer_profile", {})
            mapped_replay = _optimizer_replay_history(schema, payload)
            if mapped_replay is None:
                transaction_history = _transaction_history_from_payload(payload) or []
            else:
                transaction_history, replay_history = mapped_replay
        else:
            self._report_progress("fetching_aric_signals")
            fetched_aric_signals = _with_retry(
                lambda: self._aric.fetch_signals(event_id, session_id)
            )
            aric_signals = _merge_aric_signals(payload, fetched_aric_signals)
            self._report_progress("fetching_customer_profile")
            customer_profile = _with_retry(
                lambda: self._host_customer.fetch_customer_profile(customer_id)
            )
            self._report_progress("fetching_transaction_history")
            transaction_history = _transaction_history_from_payload(payload)
            if transaction_history is None:
                transaction_history = _with_retry(
                    lambda: self._host_tx_history.fetch_transaction_history(
                        customer_id, account_id
                    )
                )
        if transaction_history is None:
            transaction_history = []
        history = (
            replay_history
            if replay_history is not None
            else _history_values(schema, transaction_history)
        )
        if input.skip_external_enrichment:
            personal_data_changes = payload.get("personal_data_changes", {})
        else:
            self._report_progress("fetching_personal_data_changes")
            personal_data_changes = _with_retry(
                lambda: self._host_data_changes.fetch_personal_data_changes(customer_id)
            )

        host_sources = {
            AlertSchemaDataSource.ARIC: payload,
            AlertSchemaDataSource.HOST: {
                "customer_profile": customer_profile,
                "personal_data_changes": personal_data_changes,
            },
        }
        host_input, host_labels, host_roles, missing = _schema_values(
            schema, host_sources
        )
        aric_input.update(host_input)
        labels.update(host_labels)
        roles.update(host_roles)
        if missing:
            raise MandatoryAlertDataMissingError(missing)

        enrichment_note = (
            "used snapshot-only enrichment; external ARIC, customer-profile, "
            "and history lookups were not run, so missing values mean unavailable "
            "rather than negative evidence; BioCatch flags come from the alert's "
            "own fields; identity/date fields in the alert "
            "payload are not verified identity records; mapped snapshot history "
            "is the only history evidence when present; "
            if input.skip_external_enrichment
            else "fetched ARIC signals, host customer profile, "
        )
        note = (
            f"pre_process: validated schema version {schema.version}, "
            f"{len(aric_input)} input field(s), {len(labels)} label(s); "
            f"{enrichment_note}"
            f"{len(transaction_history)} transaction history record(s), "
            f"{len(personal_data_changes)} personal data change record(s)."
        )

        return PreProcessAlertOutput(
            schema_version=schema.version,
            input=aric_input,
            labels=labels,
            history=history,
            roles=roles,
            enrichment={
                "aric_signals": aric_signals,
                "customer_profile": customer_profile,
                "transaction_history": transaction_history,
                "personal_data_changes": personal_data_changes,
            },
            pre_process_note=note,
            mandatory_fields={
                field.field: aric_input[field.field]
                for field in schema.fields
                if field.is_mandatory and field.field in aric_input
            },
            optional_fields={
                # Compatibility view for old workflow-step readers; the
                # schema-shaped input above is the authoritative contract.
                **aric_input,
            },
        )
