from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI

from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMMessageRole,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.core.config import genai_config

_PROVIDER = "azure_openai"

_ROLE_TO_MESSAGE_CLS = {
    LLMMessageRole.SYSTEM: SystemMessage,
    LLMMessageRole.USER: HumanMessage,
    LLMMessageRole.ASSISTANT: AIMessage,
}


class LangchainLLMUnitOfWork(LLMUnitOfWork):
    """One logical LLM operation (e.g. "write_email"). Every `invoke` is
    instrumented through the monitoring instance it was built with."""

    def __init__(
        self,
        client: AzureChatOpenAI,
        monitoring: MonitoringPort,
        operation_name: str,
        model: str,
    ) -> None:
        self._client = client
        self._monitoring = monitoring
        self._operation_name = operation_name
        self._model = model

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        with self._monitoring.start(
            self._operation_name,
            "llm",
            metadata={
                "operation_name": self._operation_name,
                "provider": _PROVIDER,
                "model": self._model,
            },
        ) as span:
            span.write_input(
                {
                    "messages": [
                        {"role": m.role.value, "content": m.content}
                        for m in messages
                    ]
                }
            )

            response = self._client.invoke(
                [
                    _ROLE_TO_MESSAGE_CLS[m.role](content=m.content)
                    for m in messages
                ]
            )

            usage = getattr(response, "usage_metadata", None) or {}
            finish_reason = (response.response_metadata or {}).get(
                "finish_reason"
            )
            result = LLMInvocationResult(
                content=response.content,
                model=self._model,
                finish_reason=finish_reason,
                input_tokens=usage.get("input_tokens"),
                output_tokens=usage.get("output_tokens"),
            )

            span.write_result(
                {
                    "content": result.content,
                    "finish_reason": result.finish_reason,
                }
            )
            span.write_operation_metas(
                {
                    "response_model": result.model,
                    "finish_reason": result.finish_reason,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            )
            return result


class LangchainAzureLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        client = AzureChatOpenAI(
            azure_endpoint=genai_config.OPENAI_ENDPOINT,
            api_key=genai_config.OPENAI_KEY,
            api_version=genai_config.OPENAI_VERSION,
            azure_deployment=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LangchainLLMUnitOfWork(
            client=client,
            monitoring=monitoring,
            operation_name=operation_name,
            model=model,
        )
