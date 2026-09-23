from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from src.application.dtos.analyst_review_alert_dtos import (
    VALID_ANALYST_DECISIONS,
    AnalystReviewAlertInput,
    AnalystReviewAlertOutput,
)
from src.application.ports.configuration_port import AnalystPlaybook
from src.application.ports.fraud_playbook_port import (
    FraudPlaybookRecord,
    FraudPlaybookRepository,
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
    ResolveAnalystPlaybookUseCase,
)

_FALLBACK_CLASSIFICATION = "unknown"

# Used only when the playbook repository has neither the alert's
# classification nor the "unknown" fallback row seeded - keeps the
# decision agent from hard-failing on an unseeded environment.
_FALLBACK_PLAYBOOK = FraudPlaybookRecord(
    classification=_FALLBACK_CLASSIFICATION,
    title="No playbook available",
    steps=["No playbook was found for this classification - prefer escalating to a human analyst."],
    created_at=datetime.fromtimestamp(0, tz=timezone.utc),
    updated_at=datetime.fromtimestamp(0, tz=timezone.utc),
)

_SAFE_DEFAULT_DECISION = "scale_to_analyst"

_SYSTEM_PROMPT = (
    "Eres un agente de decisión de operaciones de fraude. Se te entrega el "
    "playbook de fraude para la clasificación de esta alerta y la "
    "capacidad operativa actual (analistas disponibles, cupos de "
    "voicebot, cupos de bidi y el estado de cada canal). Si se incluye "
    "\"modus_operandi_playbook\", es un playbook más específico - "
    "escrito para el patrón de fraude concreto que más se parece a esta "
    "alerta - y debe pesar más que el playbook genérico de clasificación "
    "en caso de conflicto entre ambos. Decide la única siguiente acción "
    "para esta alerta.\n\n"
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
    "canal no es \"unavailable\" y tiene capacidad disponible mayor a "
    "cero. Si el canal que elegirías no tiene capacidad, prefiere la "
    "siguiente mejor opción disponible, favoreciendo scale_to_analyst "
    "como respaldo seguro ante la duda.\n\n"
    "Responde con SOLO este JSON, nada más:\n"
    '{"decision": "block|pass|bidi|voicebot|scale_to_analyst", '
    '"reasoning": "<justificación breve>"}'
)

_USER_PROMPT = "Playbook, capacidad operativa y clasificación:\n{data}"


def _channel_data(capacity: OperationsCapacityRecord) -> dict[str, dict[str, object]]:
    return {
        "analysts": {
            "available": capacity.analysts.available,
            "status": capacity.analysts.status,
        },
        "voicebot": {
            "available": capacity.voicebot.available,
            "status": capacity.voicebot.status,
        },
        "bidi": {
            "available": capacity.bidi.available,
            "status": capacity.bidi.status,
        },
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
        fraud_playbook_port: FraudPlaybookRepository,
        operations_capacity_port: OperationsCapacityPort,
        resolve_analyst_playbook: ResolveAnalystPlaybookUseCase,
        system_prompt: str | None = None,
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
        # Segment-derived, like ClassifyAlertUseCase's enabled_tools/
        # watchlist_ids - built per call by get_analyst_review_alert_use_case
        # from the active segment, not stable adapter state.
        playbooks: list[AnalystPlaybook] | None = None,
        vector_store_instance_id: str | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._system_prompt = system_prompt or _SYSTEM_PROMPT
        self._fraud_playbook_port = fraud_playbook_port
        self._operations_capacity_port = operations_capacity_port
        self._resolve_analyst_playbook = resolve_analyst_playbook
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id
        self._playbooks = playbooks or []
        self._vector_store_instance_id = vector_store_instance_id

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

    def _get_playbook(self, fraud_classification: str) -> FraudPlaybookRecord:
        playbook = self._fraud_playbook_port.get(fraud_classification)
        if playbook is not None:
            return playbook
        playbook = self._fraud_playbook_port.get(_FALLBACK_CLASSIFICATION)
        return playbook if playbook is not None else _FALLBACK_PLAYBOOK

    def execute(self, input: AnalystReviewAlertInput) -> AnalystReviewAlertOutput:
        self._report_progress("fetching_playbook")
        playbook = self._get_playbook(input.classification.fraud_classification)
        self._report_progress("resolving_modus_operandi_playbook")
        modus_operandi_playbook = self._resolve_analyst_playbook.execute(
            f"{input.classification.fraud_classification}. "
            f"{input.classification.reasoning}".strip(),
            vector_store_instance_id=self._vector_store_instance_id,
            playbooks=self._playbooks,
        )
        self._report_progress("fetching_operations_capacity")
        capacity = self._operations_capacity_port.get_capacity()

        self._report_progress("deciding")
        uow = self._llm_factory.create(
            model=self._model,
            monitoring=self._monitoring,
            operation_name="analyst",
        )
        data = {
            "classification": {
                "is_fraud": input.classification.is_fraud,
                "fraud_classification": input.classification.fraud_classification,
                "reasoning": input.classification.reasoning,
            },
            "playbook": {
                "title": playbook.title,
                "steps": playbook.steps,
            },
            "operations_capacity": _channel_data(capacity),
        }
        if modus_operandi_playbook is not None:
            data["modus_operandi_playbook"] = {
                "name": modus_operandi_playbook.name,
                "strategy": modus_operandi_playbook.strategy,
            }
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
            playbook_title=playbook.title,
            playbook_steps=playbook.steps,
            operations_capacity=_channel_data(capacity),
            modus_operandi_playbook_name=(
                modus_operandi_playbook.name
                if modus_operandi_playbook is not None
                else None
            ),
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
        )
