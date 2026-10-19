from functools import lru_cache

from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.infrastructure.core.config import genai_config


@lru_cache(maxsize=1)
def get_llm_unit_of_work_factory() -> LLMUnitOfWorkFactory:
    backend = genai_config.LLM_BACKEND.strip().lower()
    if backend == "azure":
        from src.infrastructure.llm.langchain.azure_llm_unit_of_work import (
            LangchainAzureLLMUnitOfWorkFactory,
        )

        return LangchainAzureLLMUnitOfWorkFactory()
    if backend == "bedrock":
        from src.infrastructure.llm.langchain.bedrock_llm_unit_of_work import (
            LangchainBedrockLLMUnitOfWorkFactory,
        )

        return LangchainBedrockLLMUnitOfWorkFactory()
    if backend == "scripted_e2e":
        if genai_config.GENAI_ENVIRONMENT != "local":
            raise ValueError("scripted_e2e LLM backend is available only locally")
        from src.infrastructure.llm.scripted_e2e import (
            ScriptedE2ELLMUnitOfWorkFactory,
        )

        return ScriptedE2ELLMUnitOfWorkFactory()

    raise ValueError(f"Unsupported LLM backend: {backend}")
