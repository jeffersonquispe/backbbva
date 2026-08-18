from __future__ import annotations

from langchain_aws import ChatBedrock

from src.application.ports.llm_unit_of_work_port import (
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain._chat_model_unit_of_work import (
    LangchainChatModelUnitOfWork,
)

_PROVIDER = "aws_bedrock"


class LangchainBedrockLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        # `model` is the Bedrock model/inference-profile id (e.g.
        # "us.anthropic.claude-sonnet-4-6") - same per-step config vars
        # (PROFILING_LLM_MODEL etc.) the Azure adapter reads as a deployment
        # name, just interpreted differently per provider. Credentials are
        # never read here: boto3's default chain (AWS_ACCESS_KEY_ID/
        # AWS_SECRET_ACCESS_KEY/IAM role) resolves them, same as every other
        # boto3 client in this codebase (see config.py's SSM/Secrets
        # Manager clients).
        client = ChatBedrock(
            model_id=model,
            region_name=genai_config.AWS_REGION_NAME,
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
