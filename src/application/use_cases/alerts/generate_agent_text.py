from __future__ import annotations

from src.application.dtos.generate_agent_text_dtos import (
    GenerateAgentTextInput,
    GenerateAgentTextOutput,
)
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import LLMMessage, LLMMessageRole
from src.application.ports.monitoring_port import MonitoringPort

# Shared single-shot "system prompt + already-rendered user prompt -> text"
# use case: no tool loop, no ReAct protocol - the executor step's free-text
# generators (ARIC marking comment, Documentador's "agent" strategy) are
# both this same shape with a different system_prompt/operation_name, so
# they share one implementation instead of two near-duplicates.


class GenerateAgentTextUseCase:
    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
        system_prompt: str,
        operation_name: str,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._system_prompt = system_prompt
        self._operation_name = operation_name

    def execute(self, input: GenerateAgentTextInput) -> GenerateAgentTextOutput:
        uow = self._llm_factory.create(
            model=self._model,
            monitoring=self._monitoring,
            operation_name=self._operation_name,
        )
        result = uow.invoke(
            [
                LLMMessage(role=LLMMessageRole.SYSTEM, content=self._system_prompt),
                LLMMessage(role=LLMMessageRole.USER, content=input.prompt),
            ]
        )
        return GenerateAgentTextOutput(
            text=result.content,
            input_tokens=result.input_tokens or 0,
            output_tokens=result.output_tokens or 0,
        )
