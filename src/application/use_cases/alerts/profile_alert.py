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
    "Eres un asistente de analista de fraude. Escribe una descripción de "
    "perfil concisa y objetiva, basada únicamente en los datos dados, sin "
    "especular."
)

_PROFILE_PROMPTS: dict[str, str] = {
    "user_profile": (
        "Describe el perfil del usuario (cliente): quién es y cualquier "
        "señal de identidad o comportamiento relevante, con base en estos "
        "datos:\n{data}"
    ),
    "transaction_profile": (
        "Describe el perfil de la transacción en revisión: sus "
        "características clave y cualquier anomalía, con base en estos "
        "datos:\n{data}"
    ),
    "transactional_profile": (
        "Describe el perfil transaccional del usuario: su comportamiento "
        "o historial habitual de transacciones y cómo se compara la "
        "transacción actual, con base en estos datos:\n{data}"
    ),
}


def _serializable(value: Any) -> Any:
    return dataclasses.asdict(value) if dataclasses.is_dataclass(value) else value


_PROFILING_OPERATIONS = ("user_profile", "transaction_profile", "transactional_profile")


class ProfileAlertUseCase:
    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
        system_prompt: str | None = None,
        extra_instructions: dict[str, str] | None = None,
        status_reporter: WorkflowStatusReporter | None = None,
        workflow_execution_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        extra_instructions = extra_instructions or {}
        self._system_prompts: dict[str, str] = {}
        for op in _PROFILING_OPERATIONS:
            if system_prompt is not None:
                # Full replace - test-run admin override, wins outright
                # over any segment-level extra_instructions.
                self._system_prompts[op] = system_prompt
            elif extra_instructions.get(op):
                self._system_prompts[op] = (
                    _SYSTEM_PROMPT
                    + "\n\nInstrucciones adicionales para este segmento:\n"
                    + extra_instructions[op]
                )
            else:
                self._system_prompts[op] = _SYSTEM_PROMPT
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
                LLMMessage(
                    role=LLMMessageRole.SYSTEM,
                    content=self._system_prompts[operation_name],
                ),
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content=_PROFILE_PROMPTS[operation_name].format(
                        data=json.dumps(data, default=str)
                    ),
                ),
            ]
        )
        self._input_tokens += result.input_tokens or 0
        self._output_tokens += result.output_tokens or 0
        return result.content

    def execute(self, input: ProfileAlertInput) -> ProfileAlertOutput:
        self._input_tokens = 0
        self._output_tokens = 0
        pre_process = input.pre_process
        enrichment = {
            key: _serializable(value) for key, value in pre_process.enrichment.items()
        }
        base_data = {
            "input": pre_process.input,
            "history": pre_process.history,
            "roles": pre_process.roles,
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
            transaction_profile=self._infer("transaction_profile", transaction_data),
            transactional_profile=self._infer(
                "transactional_profile", transactional_data
            ),
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
        )
