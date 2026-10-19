from typing import Any

from src.application.ports.agent_structured_generator_port import (
    AgentStructuredGenerationInput,
)
from src.application.ports.llm_unit_of_work_port import LLMInvocationResult, LLMMessage
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.infrastructure.agents.llm_structured_agent_generator import (
    LLMStructuredAgentGenerator,
)


class InMemorySpan(MonitoringSpan):
    def write_input(self, data: dict[str, Any]) -> None:
        pass

    def write_result(self, data: dict[str, Any]) -> None:
        pass

    def write_inner_logs(self, entries: dict[str, Any] | list[dict[str, Any]]) -> None:
        pass

    def write_operation_metas(self, metadata: dict[str, Any]) -> None:
        pass

    def record_dependency(self, name: str, kind: str, metadata=None) -> None:
        pass

    def finish(self, error: str | None = None) -> None:
        pass


class InMemoryMonitoring(MonitoringPort):
    def start(self, operation_name: str, operation_type: str, metadata=None):
        return InMemorySpan()


class InMemoryUnitOfWork:
    def __init__(self, monitoring: MonitoringPort) -> None:
        self.monitoring = monitoring
        self.messages: list[LLMMessage] = []

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        self.messages = messages
        return LLMInvocationResult(
            content='{"draft":{"title":"borrador"}}', model="test-model"
        )


class InMemoryLLMFactory:
    def create(self, *, model, monitoring, operation_name, temperature=0.0, max_tokens=None):
        self.unit_of_work = InMemoryUnitOfWork(monitoring)
        return self.unit_of_work


def test_generator_returns_raw_json_under_its_own_system_contract() -> None:
    llm_factory = InMemoryLLMFactory()
    generator = LLMStructuredAgentGenerator(
        llm_factory=llm_factory,
        monitoring=InMemoryMonitoring(),
        model="test-model",
    )

    output = generator.generate(
        AgentStructuredGenerationInput(
            system_prompt="Devuelve solo el objeto JSON del borrador.",
            persisted_context='{"operation":"create"}',
            masked_user_message="Crear entidad.",
        )
    )

    assert output == '{"draft":{"title":"borrador"}}'
    assert llm_factory.unit_of_work.messages[0].content == (
        "Devuelve solo el objeto JSON del borrador."
    )
    assert "\"text\":\"respuesta\"" not in llm_factory.unit_of_work.messages[0].content
