from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.runtime_defaults import DEFAULT_ID_GENERATOR


@dataclass(frozen=True)
class IngestModusOperandiInput:
    text: str
    vector_store_id: str
    vector_store_version: int
    taxonomia_id: UUID
    taxonomia: str
    # The source ModusOperandiLibraryEntry.id - see
    # ModusOperandiDocument.library_id's docstring for why this is carried
    # separately from the document's own generated id.
    library_id: str
    # See IngestTaxonomiaInput.text_embedded - same recycle-if-possible rule.
    text_embedded: list[float] | None = None


class IngestModusOperandiUseCase:
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

    def execute(self, data: IngestModusOperandiInput) -> ModusOperandiDocument:
        taxonomia = self._repository.get(data.taxonomia_id)
        if taxonomia is None or taxonomia.type != DocumentType.TAXONOMIA:
            raise ValueError(f"taxonomia {data.taxonomia_id} does not exist")

        text_embedded = data.text_embedded
        if text_embedded is None:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="ingest_modus_operandi",
            )
            text_embedded = uow.embed([data.text]).vectors[0]
        document = ModusOperandiDocument(
            id=self._id_generator.new_id(),
            text=data.text,
            text_embedded=text_embedded,
            vector_store_id=data.vector_store_id,
            vector_store_version=data.vector_store_version,
            taxonomia_id=data.taxonomia_id,
            taxonomia=data.taxonomia,
            similar_cases=[],
            flags=[],
            library_id=data.library_id,
        )
        created = self._repository.create(document)
        assert isinstance(created, ModusOperandiDocument)
        return created
