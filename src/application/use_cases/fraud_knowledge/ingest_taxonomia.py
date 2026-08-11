from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import TaxonomiaDocument
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.monitoring_port import MonitoringPort


@dataclass(frozen=True)
class IngestTaxonomiaInput:
    text: str
    segmento: str
    configuration: str
    version: int
    activate: bool = True


class IngestTaxonomiaUseCase:
    """Taxonomias are self-sustained — no parent to validate."""

    def __init__(
        self,
        repository: FraudKnowledgeRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
    ) -> None:
        self._repository = repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model

    def execute(self, data: IngestTaxonomiaInput) -> TaxonomiaDocument:
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="ingest_taxonomia",
        )
        embedding = uow.embed([data.text])
        document = TaxonomiaDocument(
            id=uuid4(),
            text=data.text,
            text_embedded=embedding.vectors[0],
            segmento=data.segmento,
            configuration=data.configuration,
            version=data.version,
            activate=data.activate,
        )
        return self._repository.create(document)
