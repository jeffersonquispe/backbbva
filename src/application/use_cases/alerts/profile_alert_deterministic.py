from __future__ import annotations

import statistics
import unicodedata
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
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.domain.workflows.entities import (
    WorkflowStepStatus,
)

_ARIC_FLAG_LABELS = (
    ("is_mobile_rat", "RAT móvil"),
    ("is_emulator_rat", "RAT de emulador"),
    ("is_rat", "RAT"),
    ("is_bot", "bot"),
    ("ind_robo1", "indicador de robo"),
    ("is_on_call_active", "llamada activa"),
    ("is_voip_on_call", "llamada VoIP activa"),
    ("screen_broadcast", "transmisión de pantalla"),
)

_MAX_AMOUNT_ROLE_LABELS = {
    "breb": "Bre-B",
    "card withdrawals": "retiros con tarjeta",
    "payment gateway": "pasarela",
    "pse": "PSE",
    "glomo": "GloMo",
    "net": "Net",
    "loan": "préstamos",
    "bills": "facturas",
}


def _historical_maxima(
    fields: dict[str, Any], roles: dict[str, Any]
) -> list[tuple[str, float]]:
    """Return selected, schema-backed historical maxima without fixed aliases."""
    values: list[tuple[str, float]] = []
    seen: set[str] = set()

    # Schema roles let the manager keep the meaning stable while changing the
    # source field name. The role suffix is only a display label.
    for role, value in roles.items():
        if role.startswith("max_amount_") and (amount := _to_float(value)) is not None:
            label = role.removeprefix("max_amount_").replace("_", " ")
            label = _MAX_AMOUNT_ROLE_LABELS.get(label, label)
            source_name = next(
                (
                    name
                    for name, source_value in fields.items()
                    if source_value == value
                ),
                None,
            )
            values.append((label, amount))
            if source_name is not None:
                seen.add(_normalized_field_name(str(source_name)))

    # Existing flat exports predate schema roles. They are still manager
    # selected fields, so expose their source name as the label rather than
    # requiring a hard-coded product catalogue.
    for name, value in fields.items():
        normalized = _normalized_field_name(str(name))
        role_name = normalized.removeprefix("max_amount_")
        if normalized in seen:
            continue
        if normalized.startswith("max_amount_"):
            label = role_name.replace("_", " ")
            label = _MAX_AMOUNT_ROLE_LABELS.get(label, label)
        elif normalized.startswith("montomasalto"):
            label = str(name)
        else:
            continue
        if label:
            if (amount := _to_float(value)) is not None:
                values.append((label, amount))
                seen.add(normalized)
    return values


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalized_field_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _last_modified_field(
    fields: dict[str, Any], roles: dict[str, Any]
) -> tuple[str, Any] | None:
    """Resolve the configurable customer-modification timestamp, when present.

    A schema may map any source field to the optional ``customer_last_modified``
    role. For older schemas without that role, recognize common field-name
    variants so the profile does not contradict an available source timestamp.
    """
    mapped = roles.get("customer_last_modified")
    if mapped is not None:
        return "customer_last_modified", mapped
    for name, value in fields.items():
        normalized = _normalized_field_name(str(name))
        if value is not None and any(
            token in normalized
            for token in ("modificacion", "modification", "modified", "last_updated")
        ):
            return str(name), value
    return None


def _narrate_user(
    customer_profile: Any,
    personal_data_changes: list[Any],
    mandatory: dict[str, Any],
    roles: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    roles = roles or {}

    name = getattr(customer_profile, "customer_name", None)
    document = getattr(customer_profile, "document_number", None)
    address = getattr(customer_profile, "address", None)
    if name:
        identity = f"El cliente está identificado como {name}"
        identity += f" (documento {document})" if document else ""
        parts.append(identity + ".")
    else:
        parts.append(
            "El servicio de perfilamiento no encontró un registro enlazado con "
            "nombre o documento para esta alerta; esto no permite afirmar que "
            "no existan otros atributos del cliente en los datos recibidos."
        )
    if address:
        parts.append(f"Dirección registrada: {address}.")

    if personal_data_changes:
        recent = ", ".join(
            f"{c.changed_field} el {c.changed_at}" for c in personal_data_changes[:5]
        )
        parts.append(
            f"{len(personal_data_changes)} cambio(s) de datos personales "
            f"registrados, el más reciente: {recent}."
        )
    else:
        parts.append(
            "La fuente de cambios de datos personales no reportó registros; "
            "esos cambios no están disponibles para esta revisión y esta ausencia "
            "de reporte no confirma que no hayan ocurrido."
        )

    last_modified = _last_modified_field(mandatory, roles)
    if last_modified is not None:
        field_name, value = last_modified
        parts.append(
            f"El campo de fecha de modificación {field_name} contiene {value}; "
            "esto indica una modificación registrada, pero no identifica qué dato "
            "cambió ni permite evaluar su naturaleza o relación con la alerta. "
            "Conviene revisar el detalle de ese cambio si está disponible."
        )

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
    transaction_history: list[TransactionHistoryEntry],
    roles: dict[str, Any] | None = None,
) -> str:
    roles = roles or {}
    amount = roles.get("amount")
    channel = roles.get("channel")
    integration_point = roles.get("entrypoint")
    merchant = mandatory.get("merchant_name") or mandatory.get("merchant_id")
    rules = mandatory.get("rules")
    counterparty = mandatory.get("counterparty")

    summary = (
        f"Esta es una transacción de tipo {channel} por {amount}"
        if amount
        else (f"Esta es una transacción de tipo {channel}")
    )
    summary += f" vía {integration_point}" if integration_point else ""
    summary += f", hacia {merchant}" if merchant else ""
    parts = [summary + "."]

    if rules:
        parts.append(f"Activó la(s) siguiente(s) regla(s): {rules}.")

    scores = []
    for key, label in (("biocatch_score", "BioCatch"), ("model_score", "modelo")):
        value = roles.get(key, mandatory.get(key))
        if value is not None:
            scores.append(f"{label}: {value}")
    if scores:
        parts.append("Puntajes de riesgo: " + ", ".join(scores) + ".")
        parts.append(
            "El perfil no incluye la escala ni el umbral operativo de esos "
            "puntajes. Son valores presentes y potencialmente informativos, "
            "pero no se pueden calificar como altos o bajos ni descartarse "
            "como neutros solo por su valor numérico."
        )

    signal_values = [
        getattr(aric_signals, attr, None) for attr, _label in _ARIC_FLAG_LABELS
    ]
    flags = [
        label
        for (attr, label) in _ARIC_FLAG_LABELS
        if getattr(aric_signals, attr, None) is True
    ]
    if flags:
        parts.append(f"BioCatch marcó esta sesión como: {', '.join(flags)}.")
    elif not any(value is not None for value in signal_values):
        parts.append(
            "No se recibieron flags de comportamiento interpretables (RAT, bot, "
            "llamada o pantalla); estos flags no están disponibles, no se han "
            "verificado como limpios. Los puntajes numéricos listados arriba son "
            "señales distintas y no se deben confundir con estos flags."
        )
    elif any(value is None for value in signal_values):
        parts.append(
            "Entre los flags de comportamiento disponibles no se reportaron "
            "anomalías; otros flags no están disponibles, por lo que esto no "
            "permite afirmar su ausencia ni descartar riesgo. Los puntajes "
            "numéricos listados arriba son señales distintas."
        )
    else:
        parts.append(
            "BioCatch no reportó señales anómalas entre los indicadores " "revisados."
        )

    historical_counterparties = {
        entry.counterparty.strip().casefold()
        for entry in transaction_history
        if entry.counterparty and entry.counterparty.strip()
    }
    if (
        counterparty
        and integration_point
        and str(counterparty).strip().casefold()
        == str(integration_point).strip().casefold()
    ):
        parts.append(
            f"El valor de contraparte {counterparty} coincide con el punto de "
            "entrada y no identifica por sí solo un comercio o beneficiario "
            "específico; no se usa como coincidencia de destino con el historial."
        )
        counterparty = None

    if counterparty and historical_counterparties:
        if str(counterparty).strip().casefold() not in historical_counterparties:
            parts.append(
                "La contraparte actual no aparece en las transacciones del "
                "historial disponible para este cliente."
            )
        else:
            parts.append(
                "La contraparte actual también aparece en el historial "
                "disponible; esa coincidencia no demuestra por sí sola "
                "que sea habitual para el cliente."
            )
    elif counterparty:
        parts.append(
            f"La alerta identifica la contraparte actual como {counterparty}, "
            "pero el historial disponible no contiene una contraparte "
            "comparable."
        )
    elif integration_point and historical_counterparties:
        history_values = ", ".join(sorted(historical_counterparties)[:5])
        if any(
            value == str(integration_point).strip().casefold()
            for value in historical_counterparties
        ):
            parts.append(
                f"El punto de entrada informado es {integration_point}; no hay "
                "un identificador específico de comercio o beneficiario en la "
                "alerta para compararlo. El historial registra la categoría "
                f"genérica {integration_point} como contraparte ({history_values}), "
                "pero esto no identifica el mismo destino ni demuestra "
                "recurrencia de beneficiario."
            )
        else:
            parts.append(
                f"El punto de entrada informado es {integration_point}; no hay "
                "un identificador específico de comercio o beneficiario en la "
                f"alerta para compararlo. El historial contiene contraparte(s) "
                f"{history_values}; el punto de entrada y la contraparte son "
                "campos distintos y no deben tratarse como una comparación directa."
            )
    elif integration_point:
        parts.append(
            f"El punto de entrada informado es {integration_point}; la alerta "
            "no contiene un identificador específico de comercio o beneficiario."
        )
    elif historical_counterparties:
        history_values = ", ".join(sorted(historical_counterparties)[:5])
        parts.append(
            "La alerta no contiene una contraparte actual para comparar; "
            f"el historial contiene contraparte(s) {history_values}."
        )
    else:
        parts.append("No había destino/contraparte disponible para evaluar.")

    return " ".join(parts)


def _narrate_transactional(
    transaction_history: list[TransactionHistoryEntry],
    current_amount: float | None,
    fields: dict[str, Any],
    roles: dict[str, Any] | None = None,
) -> str:
    parts: list[str] = []
    roles = roles or {}
    historical_maxima = [
        f"{label}: {value:,.0f}" for label, value in _historical_maxima(fields, roles)
    ]
    if historical_maxima:
        parts.append(
            "Techos históricos por producto: " + ", ".join(historical_maxima) + "."
        )

    if not transaction_history:
        parts.append("No hay historial de transacciones disponible para este cliente.")
        return " ".join(parts)

    amounts = [t.amount for t in transaction_history if t.amount is not None]
    types = Counter(t.event_type for t in transaction_history)
    times = sorted(t.event_time for t in transaction_history if t.event_time)

    summary = (
        f"El cliente tiene {len(transaction_history)} transacción(es) registrada(s)"
    )
    summary += f", entre {times[0]} y {times[-1]}" if times else ""
    parts.append(summary + ".")

    current_time = roles.get("event_time")
    if current_time and times:
        current_timestamp = str(current_time)
        current_clock = current_timestamp.split("T")[-1].removesuffix("Z")
        historical_clocks = [
            str(value).split("T")[-1].removesuffix("Z") for value in times
        ]
        if historical_clocks and all(
            value == current_clock for value in historical_clocks
        ):
            parts.append(
                f"La transacción actual y las {len(historical_clocks)} transacción(es) "
                f"histórica(s) disponible(s) tienen la misma hora ({current_clock}); "
                "conviene validar si corresponde a una programación o a un artefacto "
                "de timestamp/normalización. Por sí solo no identifica automatización "
                "fraudulenta ni permite salir de unknown."
            )

    median_amount = statistics.median(amounts) if amounts else None
    min_amount = min(amounts) if amounts else None
    max_amount = max(amounts) if amounts else None
    if amounts:
        parts.append(
            f"Los montos históricos van de {min(amounts):,.0f} a "
            f"{max_amount:,.0f}, con una mediana de {median_amount:,.0f}."
        )

    if types:
        breakdown = ", ".join(f"{t} ({n})" for t, n in types.most_common(5))
        parts.append(f"Tipo(s) de transacción más común(es): {breakdown}.")

    comparison_counts: list[str] = []
    current_channel = roles.get("channel")
    if current_channel:
        matches = sum(
            entry.channel is not None
            and entry.channel.strip().casefold()
            == str(current_channel).strip().casefold()
            for entry in transaction_history
        )
        comparison_counts.append(
            f"canal {current_channel}: {matches}/{len(transaction_history)}"
        )
    current_type = roles.get("event_type")
    if current_type:
        matches = sum(
            entry.event_type.strip().casefold() == str(current_type).strip().casefold()
            for entry in transaction_history
        )
        comparison_counts.append(
            f"tipo {current_type}: {matches}/{len(transaction_history)}"
        )
    if current_amount is not None:
        amount_matches = sum(
            entry.amount is not None and entry.amount == current_amount
            for entry in transaction_history
        )
        comparison_counts.append(
            f"monto {current_amount:,.0f}: {amount_matches}/{len(transaction_history)}"
        )
    if comparison_counts:
        parts.append(
            "Coincidencias exactas descriptivas con el historial: "
            + "; ".join(comparison_counts)
            + ". Son coincidencias observadas, no establecen recurrencia, "
            "normalidad ni legitimidad."
        )

    statuses = Counter(t.status for t in transaction_history if t.status)
    if statuses:
        status_summary = ", ".join(
            f"{status} ({count})" for status, count in statuses.most_common(5)
        )
        parts.append(
            f"Estados reportados en el historial: {status_summary}. Estos estados "
            "describen el resultado registrado del procesamiento y no confirman "
            "por sí solos que una transacción fuera legítima o no fraudulenta."
        )

    if current_amount is not None and amounts and max_amount is not None:
        if min_amount is not None and current_amount < min_amount:
            parts.append(
                f"El monto actual de {current_amount:,.0f} está por debajo "
                f"del mínimo histórico observado ({min_amount:,.0f}); no "
                "está dentro del rango registrado."
            )
        elif current_amount > max_amount:
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
                f"El monto actual de {current_amount:,.0f} está dentro del rango "
                f"observado ({min_amount:,.0f}–{max_amount:,.0f}) en las "
                f"{len(amounts)} transacción(es) histórica(s) con monto disponible; "
                "una muestra limitada no establece por sí sola el comportamiento "
                "habitual ni es evidencia contra fraude."
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
        fields = pre_process.input
        roles = pre_process.roles
        enrichment = pre_process.enrichment
        transaction_history = enrichment.get("transaction_history") or []

        self._report_progress("user_profile")
        user_profile = _narrate_user(
            customer_profile=enrichment.get("customer_profile"),
            personal_data_changes=enrichment.get("personal_data_changes") or [],
            mandatory={
                **fields,
                "device_id": fields.get("device_id"),
                "ip_channel": fields.get("ip_channel"),
            },
            roles=roles,
        )

        self._report_progress("transaction_profile")
        transaction_profile = _narrate_transaction(
            mandatory=fields,
            aric_signals=enrichment.get("aric_signals"),
            customer_id=roles.get("customer_id"),
            transaction_history=transaction_history,
            roles=roles,
        )

        self._report_progress("transactional_profile")
        transactional_profile = _narrate_transactional(
            transaction_history=transaction_history,
            current_amount=_to_float(roles.get("amount")),
            fields=fields,
            roles=roles,
        )

        return ProfileAlertOutput(
            user_profile=user_profile,
            transaction_profile=transaction_profile,
            transactional_profile=transactional_profile,
        )
