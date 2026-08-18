from __future__ import annotations

from langchain_openai import AzureChatOpenAI

from src.application.ports.llm_unit_of_work_port import (
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
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
        client = AzureChatOpenAI(
            azure_endpoint=genai_config.OPENAI_ENDPOINT,
            api_key=genai_config.OPENAI_KEY,
            api_version=genai_config.OPENAI_VERSION,
            azure_deployment=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LangchainChatModelUnitOfWork(
            client=client,
            monitoring=monitoring,
            operation_name=operation_name,
            model=model,
            provider=_PROVIDER,
        )
