from __future__ import annotations

from src.application.dtos.generate_agent_text_dtos import GenerateAgentTextInput
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort, MonitoringSpan
from src.application.use_cases.alerts.generate_agent_text import (
    GenerateAgentTextUseCase,
)


class RecordingLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self) -> None:
        self.received_messages: list[LLMMessage] | None = None

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        self.received_messages = messages
        return LLMInvocationResult(
            content="generated text",
            model="fake-model",
            input_tokens=10,
            output_tokens=5,
        )


class RecordingLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self) -> None:
        self.created: list[RecordingLLMUnitOfWork] = []
        self.operation_names: list[str] = []
        self.models: list[str] = []

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        self.models.append(model)
        self.operation_names.append(operation_name)
        uow = RecordingLLMUnitOfWork()
        self.created.append(uow)
        return uow


class NullSpan(MonitoringSpan):
    def write_input(self, data) -> None:
        pass

    def write_result(self, data) -> None:
        pass

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata) -> None:
        pass

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error=None) -> None:
        pass


class NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return NullSpan()


def test_generate_agent_text_sends_system_and_user_prompt() -> None:
    llm_factory = RecordingLLMUnitOfWorkFactory()
    use_case = GenerateAgentTextUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        system_prompt="Eres un agente que redacta comentarios.",
        operation_name="aric_marking",
    )

    output = use_case.execute(
        GenerateAgentTextInput(prompt="Marca esta alerta: cust-1")
    )

    assert output.text == "generated text"
    assert output.input_tokens == 10
    assert output.output_tokens == 5
    assert llm_factory.operation_names == ["aric_marking"]
    assert llm_factory.models == ["fake-deployment"]
    sent = llm_factory.created[0].received_messages
    assert sent[0].content == "Eres un agente que redacta comentarios."
    assert sent[1].content == "Marca esta alerta: cust-1"
