from __future__ import annotations

import hashlib
import statistics
from collections import Counter
from typing import Any
from uuid import UUID

from src.application.dtos.profile_alert_dtos import (
    ProfileAlertInput,
    ProfileAlertOutput,
)
from src.application.ports.host_service_transaction_history_port import (
    TransactionHistoryEntry,
)
from src.application.ports.workflow_port import WorkflowStepStatus
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)

_ARIC_FLAG_LABELS = (
    ("is_mobile_rat", "RAT móvil"),
    ("is_emulator_rat", "RAT de emulador"),
    ("is_rat", "RAT"),
    ("is_bot", "bot"),
    ("is_on_call_active", "llamada activa"),
)

# New-destination detection: TransactionHistoryEntry carries no
# counterparty field today (neither the mocked host service nor the
# dataset's transacciones_json record one), so there is no real signal to
# check against. Simulated instead of omitted, per explicit instruction -
# a stable hash of (customer_id, counterparty) so the same alert always
# gets the same answer. Replace with a real lookup once destination
# history exists; this whole function goes away at that point.
_SIMULATED_NEW_DESTINATION_RATE = 30  # out of 100, arbitrary


def _simulate_is_new_destination(customer_id: str, counterparty: str) -> bool:
    digest = hashlib.sha256(f"{customer_id}:{counterparty}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < _SIMULATED_NEW_DESTINATION_RATE


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _narrate_user(
    customer_profile: Any,
    personal_data_changes: list[Any],
    mandatory: dict[str, Any],
) -> str:
    parts: list[str] = []

    name = getattr(customer_profile, "customer_name", None)
    document = getattr(customer_profile, "document_number", None)
    address = getattr(customer_profile, "address", None)
    if name:
        identity = f"El cliente está identificado como {name}"
        identity += f" (documento {document})" if document else ""
        parts.append(identity + ".")
    else:
        parts.append(
            "No se encontró un registro de identidad del cliente para "
            "esta alerta."
        )
    if address:
        parts.append(f"Dirección registrada: {address}.")

    if personal_data_changes:
        recent = ", ".join(
            f"{c.changed_field} el {c.changed_at}"
            for c in personal_data_changes[:5]
        )
        parts.append(
            f"{len(personal_data_changes)} cambio(s) de datos personales "
            f"registrados, el más reciente: {recent}."
        )
    else:
        parts.append("No hay cambios de datos personales registrados.")

    device_id = mandatory.get("device_id")
    ip = mandatory.get("ip_channel") or mandatory.get("ip_biocatch")
    user_agent = mandatory.get("user_agent")
    device_bits = [
        bit
        for bit, present in (
            (f"el dispositivo {device_id}", device_id),
            (f"la IP {ip}", ip),
            (f"el user agent {user_agent}", user_agent),
        )
        if present
    ]
    if device_bits:
        parts.append("Esta sesión se originó desde " + ", ".join(device_bits) + ".")
    else:
        parts.append(
            "No había identificadores de dispositivo o sesión disponibles "
            "para este evento."
        )

    return " ".join(parts)


def _narrate_transaction(
    mandatory: dict[str, Any],
    aric_signals: Any,
    customer_id: str | None,
) -> str:
    amount = mandatory.get("amount")
    channel = mandatory.get("channel")
    integration_point = mandatory.get("integration_point")
    merchant = mandatory.get("merchant_name") or mandatory.get("merchant_id")
    rules = mandatory.get("rules")
    counterparty = mandatory.get("counterparty")

    summary = f"Esta es una transacción de tipo {channel} por {amount}" if amount else (
        f"Esta es una transacción de tipo {channel}"
    )
    summary += f" vía {integration_point}" if integration_point else ""
    summary += f", hacia {merchant}" if merchant else ""
    parts = [summary + "."]

    if rules:
        parts.append(f"Activó la(s) siguiente(s) regla(s): {rules}.")

    flags = [
        label
        for attr, label in _ARIC_FLAG_LABELS
        if getattr(aric_signals, attr, None)
    ]
    if flags:
        parts.append(f"BioCatch marcó esta sesión como: {', '.join(flags)}.")
    else:
        parts.append(
            "No se detectaron señales anómalas de dispositivo o sesión en "
            "BioCatch."
        )

    if counterparty and customer_id:
        if _simulate_is_new_destination(customer_id, str(counterparty)):
            parts.append(
                "El destino no se había visto antes en la actividad "
                "reciente de este cliente (señal simulada - aún no hay "
                "historial real de destinos disponible)."
            )
        else:
            parts.append(
                "El destino es consistente con la actividad reciente de "
                "este cliente (señal simulada - aún no hay historial real "
                "de destinos disponible)."
            )
    else:
        parts.append("No había destino/contraparte disponible para evaluar.")

    return " ".join(parts)


def _narrate_transactional(
    transaction_history: list[TransactionHistoryEntry],
    current_amount: float | None,
) -> str:
    if not transaction_history:
        return "No hay historial de transacciones disponible para este cliente."

    amounts = [t.amount for t in transaction_history if t.amount is not None]
    types = Counter(t.event_type for t in transaction_history)
    times = sorted(t.event_time for t in transaction_history if t.event_time)

    summary = f"El cliente tiene {len(transaction_history)} transacción(es) registrada(s)"
    summary += f", entre {times[0]} y {times[-1]}" if times else ""
    parts = [summary + "."]

    median_amount = statistics.median(amounts) if amounts else None
    max_amount = max(amounts) if amounts else None
    if amounts:
        parts.append(
            f"Los montos históricos van de {min(amounts):,.0f} a "
            f"{max_amount:,.0f}, con una mediana de {median_amount:,.0f}."
        )

    if types:
        breakdown = ", ".join(f"{t} ({n})" for t, n in types.most_common(5))
        parts.append(f"Tipo(s) de transacción más común(es): {breakdown}.")

    if current_amount is not None and amounts and max_amount is not None:
        if current_amount > max_amount:
            parts.append(
                f"El monto actual de {current_amount:,.0f} supera el "
                f"monto más alto registrado ({max_amount:,.0f})."
            )
        elif median_amount and current_amount > median_amount * 3:
            parts.append(
                f"El monto actual de {current_amount:,.0f} está muy por "
                f"encima del monto habitual de este cliente "
                f"({median_amount:,.0f})."
            )
        else:
            parts.append(
                f"El monto actual de {current_amount:,.0f} está dentro "
                "del rango habitual del cliente."
            )

    return " ".join(parts)


class DeterministicProfileAlertUseCase:
    """Same contract as ProfileAlertUseCase (ProfileAlertInput ->
    ProfileAlertOutput), built by narrating pre_process's structured data
    through templates instead of calling an LLM. All three fields are
    pure description of what the data already says - no judgment/
    hypothesis involved anywhere in this DTO - so a template is a strict
    upgrade here: deterministic, free, and (for transactional_profile)
    able to use the customer's full transaction history instead of a
    token-budget-truncated slice.
    """

    def __init__(
        self,
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> None:
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id

    def _report_progress(self, detail: str) -> None:
        if self._status_reporter is None or self._workflow_execution_id is None:
            return
        self._status_reporter.report(
            WorkflowStatusUpdate(
                workflow_execution_id=self._workflow_execution_id,
                step_name="profiling",
                step_id=self._step_id,
                status=WorkflowStepStatus.RUNNING,
                detail={"output": {"progress": detail}},
            )
        )

    def execute(self, input: ProfileAlertInput) -> ProfileAlertOutput:
        pre_process = input.pre_process
        # Narration doesn't care whether pre_process filed a field as
        # mandatory or optional (that distinction only controls whether
        # its absence blocks pre_process) - merge both so e.g. device_id
        # or user_agent still show up here even though neither is
        # mandatory.
        fields = {**pre_process.optional_fields, **pre_process.mandatory_fields}
        enrichment = pre_process.enrichment
        transaction_history = enrichment.get("transaction_history") or []

        self._report_progress("user_profile")
        user_profile = _narrate_user(
            customer_profile=enrichment.get("customer_profile"),
            personal_data_changes=enrichment.get("personal_data_changes") or [],
            mandatory=fields,
        )

        self._report_progress("transaction_profile")
        transaction_profile = _narrate_transaction(
            mandatory=fields,
            aric_signals=enrichment.get("aric_signals"),
            customer_id=fields.get("customer_id"),
        )

        self._report_progress("transactional_profile")
        transactional_profile = _narrate_transactional(
            transaction_history=transaction_history,
            current_amount=_to_float(fields.get("amount")),
        )

        return ProfileAlertOutput(
            user_profile=user_profile,
            transaction_profile=transaction_profile,
            transactional_profile=transactional_profile,
        )
