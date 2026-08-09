from __future__ import annotations

import dataclasses
import json
from typing import Any
from uuid import UUID

from src.application.dtos.profile_alert_dtos import (
    ProfileAlertInput,
    ProfileAlertOutput,
)
from src.application.ports.llm_unit_of_work_port import (
    LLMMessage,
    LLMMessageRole,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.workflow_port import WorkflowStepStatus
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)

_SYSTEM_PROMPT = (
    "You are a fraud analyst assistant. Write a concise, factual profile "
    "description grounded only in the data given, no speculation."
)

_PROFILE_PROMPTS: dict[str, str] = {
    "user_profile": (
        "Describe the profile of the user (customer): who they are and any "
        "notable identity/behavioral signals, based on this data:\n{data}"
    ),
    "transaction_profile": (
        "Describe the profile of the transaction under review: its key "
        "characteristics and any anomalies, based on this data:\n{data}"
    ),
    "transactional_profile": (
        "Describe the transactional profile of the user: their typical "
        "transaction behavior/history and how the current transaction "
        "compares to it, based on this data:\n{data}"
    ),
}


def _serializable(value: Any) -> Any:
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else value


class ProfileAlertUseCase:
    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
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

    def _infer(self, operation_name: str, data: dict[str, Any]) -> str:
        self._report_progress(operation_name)
        uow = self._llm_factory.create(
            model=self._model,
            monitoring=self._monitoring,
            operation_name=operation_name,
        )
        result = uow.invoke(
            [
                LLMMessage(role=LLMMessageRole.SYSTEM, content=_SYSTEM_PROMPT),
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content=_PROFILE_PROMPTS[operation_name].format(
                        data=json.dumps(data, default=str)
                    ),
                ),
            ]
        )
        return result.content

    def execute(self, input: ProfileAlertInput) -> ProfileAlertOutput:
        pre_process = input.pre_process
        enrichment = {
            key: _serializable(value)
            for key, value in pre_process.enrichment.items()
        }
        base_data = {
            "mandatory_fields": pre_process.mandatory_fields,
            "optional_fields": pre_process.optional_fields,
        }
        user_data = {
            **base_data,
            "customer_profile": enrichment.get("customer_profile"),
            "personal_data_changes": enrichment.get("personal_data_changes"),
        }
        transaction_data = {
            **base_data,
            "aric_signals": enrichment.get("aric_signals"),
        }
        transactional_data = {
            **base_data,
            "transaction_history": enrichment.get("transaction_history"),
        }

        return ProfileAlertOutput(
            user_profile=self._infer("user_profile", user_data),
            transaction_profile=self._infer(
                "transaction_profile", transaction_data
            ),
            transactional_profile=self._infer(
                "transactional_profile", transactional_data
            ),
        )
