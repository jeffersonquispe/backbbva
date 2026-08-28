from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.monitoring_port import MonitoringPort


@dataclass(frozen=True)
class IngestModusOperandiInput:
    text: str
    segmento: str
    configuration: str
    version: int
    taxonomia_id: UUID
    taxonomia: str
    activate: bool = True


class IngestModusOperandiUseCase:
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

    def execute(self, data: IngestModusOperandiInput) -> ModusOperandiDocument:
        taxonomia = self._repository.get(data.taxonomia_id)
        if taxonomia is None or taxonomia.type != DocumentType.TAXONOMIA:
            raise ValueError(f"taxonomia {data.taxonomia_id} does not exist")

        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="ingest_modus_operandi",
        )
        embedding = uow.embed([data.text])
        document = ModusOperandiDocument(
            id=uuid4(),
            text=data.text,
            text_embedded=embedding.vectors[0],
            segmento=data.segmento,
            configuration=data.configuration,
            version=data.version,
            taxonomia_id=data.taxonomia_id,
            taxonomia=data.taxonomia,
            similar_cases=[],
            flags=[],
            activate=data.activate,
        )
        return self._repository.create(document)
