from functools import lru_cache

from src.application.ports.llm_unit_of_work_port import LLMUnitOfWorkFactory
from src.infrastructure.llm.langchain.azure_llm_unit_of_work import (
    LangchainAzureLLMUnitOfWorkFactory,
)


@lru_cache(maxsize=1)
def get_llm_unit_of_work_factory() -> LLMUnitOfWorkFactory:
    return LangchainAzureLLMUnitOfWorkFactory()
