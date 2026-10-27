from __future__ import annotations

from dataclasses import dataclass

from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.fraud_knowledge_port import TaxonomiaDocument
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.runtime_defaults import DEFAULT_ID_GENERATOR


@dataclass(frozen=True)
class IngestTaxonomiaInput:
    text: str
    vector_store_id: str
    vector_store_version: int
    # Recycled from the source TaxonomyLibraryEntry.embedding when the
    # caller (BuildVectorStoreGenerationUseCase) already has one cached for
    # this exact text - skips the embedding call entirely. None forces a
    # fresh embed, only expected as a fallback for a stray asset that
    # somehow reached a build without a cached embedding.
    text_embedded: list[float] | None = None


class IngestTaxonomiaUseCase:
    """Taxonomias are self-sustained — no parent to validate."""

    def __init__(
        self,
        repository: FraudKnowledgeRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(self, data: IngestTaxonomiaInput) -> TaxonomiaDocument:
        text_embedded = data.text_embedded
        if text_embedded is None:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="ingest_taxonomia",
            )
            text_embedded = uow.embed([data.text]).vectors[0]
        document = TaxonomiaDocument(
            id=self._id_generator.new_id(),
            text=data.text,
            text_embedded=text_embedded,
            vector_store_id=data.vector_store_id,
            vector_store_version=data.vector_store_version,
        )
        created = self._repository.create(document)
        assert isinstance(created, TaxonomiaDocument)
        return created
