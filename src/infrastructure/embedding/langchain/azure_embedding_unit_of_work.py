from __future__ import annotations

from langchain_openai import AzureOpenAIEmbeddings

from src.application.ports.embedding_port import (
    EmbeddingResult,
    EmbeddingUnitOfWork,
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.core.config import genai_config

_PROVIDER = "azure_openai"


class LangchainAzureEmbeddingUnitOfWork(EmbeddingUnitOfWork):
    """One logical embedding operation. Every `embed` is instrumented
    through the monitoring instance it was built with."""

    def __init__(
        self,
        client: AzureOpenAIEmbeddings,
        monitoring: MonitoringPort,
        operation_name: str,
        model: str,
    ) -> None:
        self._client = client
        self._monitoring = monitoring
        self._operation_name = operation_name
        self._model = model

    def embed(self, texts: list[str]) -> EmbeddingResult:
        with self._monitoring.start(
            self._operation_name,
            "embedding",
            metadata={
                "operation_name": self._operation_name,
                "provider": _PROVIDER,
                "model": self._model,
            },
        ) as span:
            span.write_input({"texts": texts})

            vectors = self._client.embed_documents(texts)

            result = EmbeddingResult(
                vectors=vectors,
                model=self._model,
                dimensions=len(vectors[0]) if vectors else 0,
            )

            span.write_result({"count": len(result.vectors)})
            span.write_operation_metas(
                {
                    "response_model": result.model,
                    "dimensions": result.dimensions,
                }
            )
            return result


class LangchainAzureEmbeddingUnitOfWorkFactory(EmbeddingUnitOfWorkFactory):
    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
    ) -> EmbeddingUnitOfWork:
        client = AzureOpenAIEmbeddings(
            azure_endpoint=genai_config.OPENAI_ENDPOINT,
            api_key=genai_config.OPENAI_KEY,
            api_version=genai_config.OPENAI_VERSION,
            azure_deployment=model,
            max_retries=5,
            request_timeout=120,
        )
        return LangchainAzureEmbeddingUnitOfWork(
            client=client,
            monitoring=monitoring,
            operation_name=operation_name,
            model=model,
        )
