from __future__ import annotations

import logging
import time

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
_MAX_PROVIDER_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 0.25
_TRANSIENT_PROVIDER_ERROR_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectTimeoutError",
    "EndpointConnectionError",
    "InternalServerError",
    "InternalServerException",
    "ModelNotReadyException",
    "ModelTimeoutException",
    "ReadTimeoutError",
    "RateLimitError",
    "ServiceUnavailableError",
    "ThrottlingException",
    "TimeoutError",
}
logger = logging.getLogger(__name__)


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
                        {"role": m.role.value, "content": m.content} for m in messages
                    ]
                }
            )

            provider_messages = [
                _ROLE_TO_MESSAGE_CLS[m.role](content=m.content) for m in messages
            ]
            retry_count = 0
            while True:
                try:
                    response = self._client.invoke(provider_messages)
                    break
                except Exception as error:  # noqa: BLE001 - provider SDKs vary by backend.
                    if (
                        retry_count >= _MAX_PROVIDER_ATTEMPTS - 1
                        or not _is_transient_provider_error(error)
                    ):
                        span.write_operation_metas(
                            {
                                "retry_count": retry_count,
                                "provider_attempts": retry_count + 1,
                                "provider_error_type": type(error).__name__,
                            }
                        )
                        raise
                    retry_count += 1
                    logger.warning(
                        "Transient LLM provider error; retrying (provider=%s, operation=%s, attempt=%s, error_type=%s)",
                        self._provider,
                        self._operation_name,
                        retry_count + 1,
                        type(error).__name__,
                    )
                    time.sleep(_RETRY_DELAY_SECONDS)

            usage = getattr(response, "usage_metadata", None) or {}
            metadata = response.response_metadata or {}
            # Different providers name this differently under langchain's
            # common response_metadata dict (OpenAI: finish_reason, Bedrock:
            # stop_reason) - try both, optional either way.
            finish_reason = metadata.get("finish_reason") or metadata.get("stop_reason")
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
                    "retry_count": retry_count,
                    "provider_attempts": retry_count + 1,
                }
            )
            return result


def _is_transient_provider_error(error: Exception) -> bool:
    if isinstance(error, (ConnectionError, TimeoutError)):
        return True
    if type(error).__name__ in _TRANSIENT_PROVIDER_ERROR_NAMES:
        return True

    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
        if isinstance(response, dict):
            metadata = response.get("ResponseMetadata", {})
            if isinstance(metadata, dict):
                status_code = metadata.get("HTTPStatusCode", status_code)
    if isinstance(status_code, int) and (
        status_code == 429 or 500 <= status_code <= 599
    ):
        return True

    if isinstance(response, dict):
        error_data = response.get("Error", {})
        code = error_data.get("Code") if isinstance(error_data, dict) else None
        return isinstance(code, str) and code in {
            "InternalServerError",
            "InternalServerException",
            "ModelNotReadyException",
            "ModelTimeoutException",
            "RequestTimeout",
            "RequestTimeoutException",
            "ServiceUnavailable",
            "ServiceUnavailableException",
            "Throttling",
            "ThrottlingException",
            "TooManyRequestsException",
        }
    return False
