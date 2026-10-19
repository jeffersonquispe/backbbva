from __future__ import annotations

from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain._chat_model_unit_of_work import (
    LangchainChatModelUnitOfWork,
)
from src.infrastructure.llm.langchain.azure_llm_unit_of_work import (
    LangchainAzureLLMUnitOfWorkFactory,
)
from tests.test_infrastructure.test_llm.test_chat_model_unit_of_work import (
    RecordingMonitoring,
)


def test_factory_wires_azure_deployment_as_model(monkeypatch):
    monkeypatch.setattr(
        genai_config, "OPENAI_ENDPOINT", "https://example.openai.azure.com"
    )
    monkeypatch.setattr(genai_config, "OPENAI_KEY", "dummy")
    monkeypatch.setattr(genai_config, "OPENAI_VERSION", "2024-08-01-preview")

    factory = LangchainAzureLLMUnitOfWorkFactory()
    uow = factory.create(
        model="agentepqrs-llm-live-agent-gpt52",
        monitoring=RecordingMonitoring(),
        operation_name="review_email",
    )

    assert isinstance(uow, LangchainChatModelUnitOfWork)
    assert uow._model == "agentepqrs-llm-live-agent-gpt52"
    assert uow._provider == "azure_openai"
    assert uow._client.deployment_name == "agentepqrs-llm-live-agent-gpt52"


def test_factory_uses_gpt5_completion_token_parameter(monkeypatch):
    monkeypatch.setattr(
        genai_config, "OPENAI_ENDPOINT", "https://example.openai.azure.com"
    )
    monkeypatch.setattr(genai_config, "OPENAI_KEY", "dummy")
    monkeypatch.setattr(genai_config, "OPENAI_VERSION", "2024-08-01-preview")

    uow = LangchainAzureLLMUnitOfWorkFactory().create(
        model="agentepqrs-llm-live-agent-gpt52",
        monitoring=RecordingMonitoring(),
        operation_name="agent_chat",
        temperature=0.0,
        max_tokens=1_200,
    )

    assert uow._client.max_tokens is None
    assert uow._client.temperature is None
    assert uow._client.model_kwargs == {"max_completion_tokens": 1_200}
