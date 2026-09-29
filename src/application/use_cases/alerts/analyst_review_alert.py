from __future__ import annotations

import json
from dataclasses import asdict
from uuid import UUID

from src.application.dtos.analyst_review_alert_dtos import (
    VALID_ANALYST_DECISIONS,
    AnalystReviewAlertInput,
    AnalystReviewAlertOutput,
)
from src.application.ports.llm_unit_of_work_port import (
    LLMMessage,
    LLMMessageRole,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.operations_capacity_port import (
    OperationsCapacityPort,
    OperationsCapacityRecord,
)
from src.application.ports.workflow_port import WorkflowStepStatus
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)
from src.application.use_cases.alerts.resolve_analyst_playbook import (
    ResolvedPlaybook,
    ResolveAnalystPlaybookUseCase,
)
from src.domain.models.prompt_template import substitute_variables

_SAFE_DEFAULT_DECISION = "scale_to_analyst"

# Applied without calling the LLM when no close modus operandi has a
# playbook: a human decides; if no analyst is available the executor falls
# back to a soft block (the playbook fallbacks default to block_soft).
_NO_PLAYBOOK_REASONING = (
    "Ningún modus operandi cercano a esta alerta tiene playbook: se escala "
    "a un analista humano (bloqueo suave si no hay analistas disponibles)."
)

_SYSTEM_PROMPT = (
    "Eres un agente de decisión de operaciones de fraude. Se te entrega la "
    "clasificación de la alerta, el playbook del modus operandi que más se "
    "le parece y la capacidad operativa actual (analistas disponibles, "
    "cupos de voicebot, cupos de bidi y el estado de cada canal). Decide la "
    "única siguiente acción para esta alerta.\n\n"
    "El playbook trae: \"strategy\" (cómo tratar este modus operandi), "
    "\"resolution\" (el método de resolución preferido) y los respaldos "
    "\"if_no_voicebot\" / \"if_no_analyst\" (qué hacer si ese recurso no "
    "tiene capacidad). Sigue el playbook: usa su método preferido si el "
    "recurso tiene capacidad y, si no, su respaldo. \"handle_by_aria\" "
    "significa que decides tú entre block, pass o bidi según la evidencia.\n\n"
    "Significado de las decisiones:\n"
    "- block: el playbook indica fraude claro y confirmado - detener la "
    "transacción/canal ahora.\n"
    "- pass: no hay indicios de fraude que requieran más acción - liberar "
    "la alerta.\n"
    "- bidi: enrutar a un canal de verificación bidireccional (chat/voz) "
    "con el cliente.\n"
    "- voicebot: enrutar al canal automatizado de verificación por "
    "voicebot.\n"
    "- scale_to_analyst: escalar a un analista humano.\n\n"
    "Solo elige bidi, voicebot o scale_to_analyst si el estado de ese "
    "canal es \"available\" y tiene capacidad disponible mayor a cero "
    "(\"exhausted\" = sin cupo ahora, \"unavailable\" = apagado). Si "
    "igual lo eliges y al ejecutar ya no hay cupo, se aplicará el respaldo "
    "del playbook automáticamente.\n\n"
    "Responde con SOLO este JSON, nada más:\n"
    '{"decision": "block|pass|bidi|voicebot|scale_to_analyst", '
    '"reasoning": "<justificación breve>"}'
)

_USER_PROMPT = "Playbook, capacidad operativa y clasificación:\n{data}"


def _channel_data(capacity: OperationsCapacityRecord) -> dict[str, dict[str, object]]:
    return {
        name: {
            "available": channel.available,
            "status": channel.status,
            "total": channel.total,
        }
        for name, channel in (
            ("analysts", capacity.analysts),
            ("voicebot", capacity.voicebot),
            ("bidi", capacity.bidi),
        )
    }


def _playbook_data(resolved: ResolvedPlaybook) -> dict[str, object]:
    return {
        "modus_operandi": resolved.modus_operandi_title,
        **json.loads(json.dumps(asdict(resolved.playbook), default=str)),
    }


def _parse_decision(raw: str) -> tuple[str, str]:
    try:
        data = json.loads(raw)
        decision = str(data.get("decision", ""))
        if decision not in VALID_ANALYST_DECISIONS:
            return _SAFE_DEFAULT_DECISION, (
                f"Model returned an invalid decision '{decision}' - "
                "defaulting to scale_to_analyst."
            )
        return decision, str(data.get("reasoning", ""))
    except (json.JSONDecodeError, AttributeError):
        return _SAFE_DEFAULT_DECISION, (
            f"Could not parse decision agent output, defaulting to "
            f"scale_to_analyst. Raw output: {raw}"
        )


class AnalystReviewAlertUseCase:
    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
        operations_capacity_port: OperationsCapacityPort,
        resolve_analyst_playbook: ResolveAnalystPlaybookUseCase,
        system_prompt: str | None = None,
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
        # Segment-derived, like ClassifyAlertUseCase's enabled_tools/
        # watchlist_ids - built per call by get_analyst_review_alert_use_case
        # from the active segment, not stable adapter state.
        vector_store_instance_id: str | None = None,
        handling_prompt: str = "",
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._system_prompt = system_prompt or _SYSTEM_PROMPT
        self._operations_capacity_port = operations_capacity_port
        self._resolve_analyst_playbook = resolve_analyst_playbook
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id
        self._vector_store_instance_id = vector_store_instance_id
        self._handling_prompt = handling_prompt

    def _report_progress(self, detail: str) -> None:
        if self._status_reporter is None or self._workflow_execution_id is None:
            return
        self._status_reporter.report(
            WorkflowStatusUpdate(
                workflow_execution_id=self._workflow_execution_id,
                step_name="analyst",
                step_id=self._step_id,
                status=WorkflowStepStatus.RUNNING,
                detail={"output": {"progress": detail}},
            )
        )

    def execute(self, input: AnalystReviewAlertInput) -> AnalystReviewAlertOutput:
        self._report_progress("resolving_modus_operandi_playbook")
        resolved = self._resolve_analyst_playbook.execute(
            f"{input.classification.fraud_classification}. "
            f"{input.classification.reasoning}".strip(),
            vector_store_instance_id=self._vector_store_instance_id,
        )
        self._report_progress("fetching_operations_capacity")
        capacity = _channel_data(self._operations_capacity_port.get_capacity())

        if resolved is None:
            return AnalystReviewAlertOutput(
                decision="scale_to_analyst",
                reasoning=_NO_PLAYBOOK_REASONING,
                operations_capacity=capacity,
            )

        self._report_progress("deciding")
        uow = self._llm_factory.create(
            model=self._model,
            monitoring=self._monitoring,
            operation_name="analyst",
        )
        playbook = _playbook_data(resolved)
        data: dict[str, object] = {
            "classification": {
                "is_fraud": input.classification.is_fraud,
                "fraud_classification": input.classification.fraud_classification,
                "reasoning": input.classification.reasoning,
            },
            "playbook": playbook,
            "operations_capacity": capacity,
        }
        if self._handling_prompt:
            data["handling_instructions"] = substitute_variables(
                self._handling_prompt,
                {
                    "modus_operandi": resolved.modus_operandi_title,
                    "playbook": playbook,
                    "voicebot_resources": capacity["voicebot"],
                    "analyst_resources": capacity["analysts"],
                },
            )
        result = uow.invoke(
            [
                LLMMessage(role=LLMMessageRole.SYSTEM, content=self._system_prompt),
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content=_USER_PROMPT.format(
                        data=json.dumps(data, default=str)
                    ),
                ),
            ]
        )
        decision, reasoning = _parse_decision(result.content)
        return AnalystReviewAlertOutput(
            decision=decision,
            reasoning=reasoning,
            modus_operandi_id=resolved.modus_operandi_id,
            modus_operandi_title=resolved.modus_operandi_title,
            playbook=resolved.playbook,
            operations_capacity=capacity,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
        )
