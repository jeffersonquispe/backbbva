from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMMessageRole,
    LLMUnitOfWork,
)
from src.application.ports.monitoring_port import MonitoringPort

_ROLE_TO_MESSAGE_CLS = {
    LLMMessageRole.SYSTEM: SystemMessage,
    LLMMessageRole.USER: HumanMessage,
    LLMMessageRole.ASSISTANT: AIMessage,
}


class LangchainChatModelUnitOfWork(LLMUnitOfWork):
    """One logical LLM operation (e.g. "write_email"). Every `invoke` is
    instrumented through the monitoring instance it was built with.

    Provider-agnostic: any langchain BaseChatModel works here the same
    way (Azure, Bedrock, ...) - only client construction differs per
    provider, which is each factory's job, not this class's.
    """

    def __init__(
        self,
        client: BaseChatModel,
        monitoring: MonitoringPort,
        operation_name: str,
        model: str,
        provider: str,
    ) -> None:
        self._client = client
        self._monitoring = monitoring
        self._operation_name = operation_name
        self._model = model
        self._provider = provider

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        with self._monitoring.start(
            self._operation_name,
            "llm",
            metadata={
                "operation_name": self._operation_name,
                "provider": self._provider,
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
            metadata = response.response_metadata or {}
            # Different providers name this differently under langchain's
            # common response_metadata dict (OpenAI: finish_reason, Bedrock:
            # stop_reason) - try both, optional either way.
            finish_reason = metadata.get("finish_reason") or metadata.get(
                "stop_reason"
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
