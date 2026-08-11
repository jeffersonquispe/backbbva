from functools import lru_cache

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.infrastructure.embedding.langchain.azure_embedding_unit_of_work import (
    LangchainAzureEmbeddingUnitOfWorkFactory,
)


@lru_cache(maxsize=1)
def get_embedding_unit_of_work_factory() -> EmbeddingUnitOfWorkFactory:
    return LangchainAzureEmbeddingUnitOfWorkFactory()
