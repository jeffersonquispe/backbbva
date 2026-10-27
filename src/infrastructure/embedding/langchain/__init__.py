from functools import lru_cache

from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.infrastructure.embedding.langchain.azure_embedding_unit_of_work import (
    LangchainAzureEmbeddingUnitOfWorkFactory,
)
from src.infrastructure.embedding.usage_meter import MeteredEmbeddingUnitOfWorkFactory


@lru_cache(maxsize=1)
def get_embedding_unit_of_work_factory() -> EmbeddingUnitOfWorkFactory:
    # Metered so optimizer sessions can attribute their embedding usage.
    return MeteredEmbeddingUnitOfWorkFactory(LangchainAzureEmbeddingUnitOfWorkFactory())
