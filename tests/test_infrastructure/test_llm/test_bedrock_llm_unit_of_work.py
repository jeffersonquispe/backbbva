from __future__ import annotations

from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain._chat_model_unit_of_work import (
    LangchainChatModelUnitOfWork,
)
from src.infrastructure.llm.langchain.bedrock_llm_unit_of_work import (
    LangchainBedrockLLMUnitOfWorkFactory,
)
from tests.test_infrastructure.test_llm.test_chat_model_unit_of_work import (
    RecordingMonitoring,
)


def test_factory_wires_model_id_and_region_from_config(monkeypatch):
    monkeypatch.setattr(genai_config, "AWS_REGION_NAME", "us-east-1")

    factory = LangchainBedrockLLMUnitOfWorkFactory()
    uow = factory.create(
        model="us.anthropic.claude-sonnet-4-6",
        monitoring=RecordingMonitoring(),
        operation_name="classify",
        temperature=0.1,
        max_tokens=1800,
    )

    assert isinstance(uow, LangchainChatModelUnitOfWork)
    assert uow._model == "us.anthropic.claude-sonnet-4-6"
    assert uow._provider == "aws_bedrock"
    assert uow._client.model_id == "us.anthropic.claude-sonnet-4-6"
    assert uow._client.region_name == "us-east-1"
    assert uow._client.temperature == 0.1
    assert uow._client.max_tokens == 1800


def test_factory_defaults_temperature_and_leaves_max_tokens_unset(monkeypatch):
    monkeypatch.setattr(genai_config, "AWS_REGION_NAME", "eu-west-1")

    factory = LangchainBedrockLLMUnitOfWorkFactory()
    uow = factory.create(
        model="us.anthropic.claude-sonnet-4-6",
        monitoring=RecordingMonitoring(),
        operation_name="classify",
    )

    assert uow._client.temperature == 0.0
    assert uow._client.max_tokens is None
