from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from src.application.dtos.analyst_review_alert_dtos import (
    VALID_ANALYST_DECISIONS,
    AnalystReviewAlertInput,
    AnalystReviewAlertOutput,
)
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
    "You are a fraud operations decision agent. You are given the fraud "
    "playbook for this alert's classification and the current operations "
    "capacity (available analysts, voicebot slots, bidi slots, and each "
    "channel's status). Decide the single next action for this alert.\n\n"
    "Decision meanings:\n"
    "- block: the playbook indicates clear, confirmed fraud - stop the "
    "transaction/channel now.\n"
    "- pass: no indication of fraud requiring further action - release "
    "the alert.\n"
    "- bidi: route to a bidirectional (chat/voice) verification channel "
    "with the customer.\n"
    "- voicebot: route to the automated voicebot verification channel.\n"
    "- scale_to_analyst: escalate to a human analyst.\n\n"
    "Only choose bidi, voicebot, or scale_to_analyst if that channel's "
    "status is not \"unavailable\" and it has available capacity greater "
    "than zero. If the channel you would otherwise choose has no "
    "capacity, prefer the next best available option, favoring "
    "scale_to_analyst as the safe fallback when unsure.\n\n"
    "Respond with ONLY this JSON, nothing else:\n"
    '{"decision": "block|pass|bidi|voicebot|scale_to_analyst", '
    '"reasoning": "<brief justification>"}'
)

_USER_PROMPT = "Playbook, operations capacity, and classification:\n{data}"


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
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._fraud_playbook_port = fraud_playbook_port
        self._operations_capacity_port = operations_capacity_port
        self._status_reporter = status_reporter
        self._workflow_execution_id = workflow_execution_id
        self._step_id = step_id

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
        result = uow.invoke(
            [
                LLMMessage(role=LLMMessageRole.SYSTEM, content=_SYSTEM_PROMPT),
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
        )
