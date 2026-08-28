from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FlagDocument,
    ModusOperandiDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.monitoring_port import MonitoringPort


@dataclass(frozen=True)
class IngestFlagInput:
    text: str
    flag_type: DocumentType  # RED_FLAG | YELLOW_FLAG
    segmento: str
    configuration: str
    version: int
    modus_operandi_ids: list[UUID]
    activate: bool = True


class IngestFlagUseCase:
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

    def execute(self, data: IngestFlagInput) -> FlagDocument:
        parents: list[ModusOperandiDocument] = []
        for modus_operandi_id in data.modus_operandi_ids:
            parent = self._repository.get(modus_operandi_id)
            if parent is None or parent.type != DocumentType.MODUS_OPERANDI:
                raise ValueError(f"modus_operandi {modus_operandi_id} does not exist")
            assert isinstance(parent, ModusOperandiDocument)
            parents.append(parent)

        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="ingest_flag",
        )
        embedding = uow.embed([data.text])
        document = FlagDocument(
            id=uuid4(),
            text=data.text,
            text_embedded=embedding.vectors[0],
            segmento=data.segmento,
            configuration=data.configuration,
            version=data.version,
            modus_operandi_ids=data.modus_operandi_ids,
            activate=data.activate,
            type=data.flag_type,
        )
        created = self._repository.create(document)

        for parent in parents:
            self._repository.update(replace(parent, flags=[*parent.flags, created.id]))

        return created
