from __future__ import annotations

import time
from typing import Any, Callable, TypeVar
from uuid import UUID

from src.application.dtos.pre_process_dtos import (
    PreProcessAlertInput,
    PreProcessAlertOutput,
)
from src.application.ports.aric_alert_port import AricAlertPort
from src.application.ports.host_service_customer_port import (
    HostServiceCustomerProfilePort,
)
from src.application.ports.host_service_personal_data_changes_port import (
    HostServicePersonalDataChangesPort,
)
from src.application.ports.host_service_transaction_history_port import (
    HostServiceTransactionHistoryPort,
)
from src.application.ports.workflow_port import WorkflowStepStatus
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.domain.alerts.exceptions import MandatoryAlertDataMissingError

MAX_FETCH_ATTEMPTS = 3

# Dotted-path candidates per mandatory data point (tried in order, first
# non-empty wins). Paths that traverse a list take its first element -
# good enough for the single-alert-object case this covers today; alerts
# carrying multiple entities/models per event need real per-item merging,
# deferred until that shape shows up.
_MANDATORY_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "rules": ("object.triggeredRules",),
    "tags": ("object.tags",),
    "triggered_models": ("object.triggeredModels",),
    "biocatch_score": ("biocatch.score",),
    "event_time": ("eventTime",),
    "event_type": ("eventType",),
    "customer_id": ("customerId",),
    "account_id": ("accountId",),
    "channel": ("channel",),
    "entry_mode": (
        "entryMode.terminalDataInputModeCapability",
        "entryMode.dataInputMode",
    ),
    "merchant_id": ("merchantId",),
    "merchant_name": ("merchantName",),
    "session_id": ("session.sessionId", "biocatch.customerSessionID"),
    "integration_point": ("integrationPoint",),
    "description": ("serviceDescription",),
    "counterparty": ("counterpartyName.fullName", "counterpartyId"),
    "amount": ("amount.baseValue",),
    "response": ("msgStatus",),
    "direction": ("direction",),
    "ip_channel": ("device.ipAddress",),
    "ip_biocatch": ("biocatch.ip",),
    "device_id": ("_metadata.searchable.deviceId",),
    "client_code": ("customerClientCode", "personalId"),
    "user_agent": ("device.userAgentString",),
    "event_id": ("eventId",),
}

# Card-only data points: mandatory, but only for card transactions.
_CARD_ONLY_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "card_bin": ("cardBIN",),
    "authorization_phase": ("authorizationPhase",),
}

# Present in the spec but flagged "no se usa" - captured when available,
# never blocks pre_process.
_OPTIONAL_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "reason_code": ("msgReason",),
    "biocatch_muid": ("biocatch.muid",),
}

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


def _is_card_transaction(payload: dict[str, Any]) -> bool:
    channel = str(_get_path(payload, "channel") or "").lower()
    return "card" in channel or _get_path(payload, "cardId") is not None


def _extract_mandatory_fields(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    field_paths = dict(_MANDATORY_FIELD_PATHS)
    if _is_card_transaction(payload):
        field_paths.update(_CARD_ONLY_FIELD_PATHS)

    extracted: dict[str, Any] = {}
    missing: list[str] = []
    for name, paths in field_paths.items():
        value = _first_present(payload, paths)
        if value is None:
            missing.append(name)
        else:
            extracted[name] = value
    return extracted, missing


def _extract_optional_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        name: value
        for name, paths in _OPTIONAL_FIELD_PATHS.items()
        if (value := _first_present(payload, paths)) is not None
    }


def _with_retry(fn: Callable[[], T], attempts: int = MAX_FETCH_ATTEMPTS) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
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
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> None:
        self._aric = aric_alert_port
        self._host_customer = host_customer_profile_port
        self._host_tx_history = host_transaction_history_port
        self._host_data_changes = host_personal_data_changes_port
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id

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
        mandatory_fields, missing = _extract_mandatory_fields(input.payload)
        if missing:
            raise MandatoryAlertDataMissingError(missing)
        optional_fields = _extract_optional_fields(input.payload)

        customer_id = str(mandatory_fields["customer_id"])
        account_id = mandatory_fields.get("account_id")
        session_id = mandatory_fields.get("session_id")
        event_id = str(mandatory_fields["event_id"])

        self._report_progress("fetching_aric_signals")
        aric_signals = _with_retry(
            lambda: self._aric.fetch_signals(event_id, session_id)
        )
        self._report_progress("fetching_customer_profile")
        customer_profile = _with_retry(
            lambda: self._host_customer.fetch_customer_profile(customer_id)
        )
        self._report_progress("fetching_transaction_history")
        transaction_history = _with_retry(
            lambda: self._host_tx_history.fetch_transaction_history(
                customer_id, account_id
            )
        )
        self._report_progress("fetching_personal_data_changes")
        personal_data_changes = _with_retry(
            lambda: self._host_data_changes.fetch_personal_data_changes(
                customer_id
            )
        )

        note = (
            f"pre_process: validated {len(mandatory_fields)} mandatory "
            f"field(s), {len(optional_fields)} optional field(s) present; "
            "fetched ARIC signals, host customer profile, "
            f"{len(transaction_history)} transaction history record(s), "
            f"{len(personal_data_changes)} personal data change record(s)."
        )

        return PreProcessAlertOutput(
            mandatory_fields=mandatory_fields,
            optional_fields=optional_fields,
            enrichment={
                "aric_signals": aric_signals,
                "customer_profile": customer_profile,
                "transaction_history": transaction_history,
                "personal_data_changes": personal_data_changes,
            },
            pre_process_note=note,
        )
