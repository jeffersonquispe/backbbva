from __future__ import annotations

from typing import Any

from langchain_openai import AzureChatOpenAI

from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import LLMUnitOfWork
from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain._chat_model_unit_of_work import (
    LangchainChatModelUnitOfWork,
)

_PROVIDER = "azure_openai"


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
        is_gpt5_deployment = "gpt5" in model.lower().replace("-", "")
        client_options: dict[str, Any] = {
            "azure_endpoint": genai_config.OPENAI_ENDPOINT,
            "api_key": genai_config.OPENAI_KEY,
            "api_version": genai_config.OPENAI_VERSION,
            "azure_deployment": model,
            "timeout": genai_config.OPENAI_REQUEST_TIMEOUT_SECONDS,
            "temperature": None if is_gpt5_deployment else temperature,
            "max_tokens": None if is_gpt5_deployment else max_tokens,
        }
        if is_gpt5_deployment and max_tokens is not None:
            client_options["model_kwargs"] = {
                "max_completion_tokens": max_tokens
            }
        client = AzureChatOpenAI(
            **client_options,
        )
        return LangchainChatModelUnitOfWork(
            client=client,
            monitoring=monitoring,
            operation_name=operation_name,
            model=model,
            provider=_PROVIDER,
        )
