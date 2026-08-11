from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID, uuid4

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
    YellowFlagDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.monitoring_port import MonitoringPort


@dataclass(frozen=True)
class IngestYellowFlagInput:
    text: str
    segmento: str
    configuration: str
    version: int
    modus_operandi_id: UUID
    taxonomia_id: UUID
    activate: bool = True


class IngestYellowFlagUseCase:
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

    def execute(self, data: IngestYellowFlagInput) -> YellowFlagDocument:
        modus_operandi = self._repository.get(data.modus_operandi_id)
        if modus_operandi is None or modus_operandi.type != DocumentType.MODUS_OPERANDI:
            raise ValueError(f"modus_operandi {data.modus_operandi_id} does not exist")
        assert isinstance(modus_operandi, ModusOperandiDocument)
        if modus_operandi.taxonomia_id != data.taxonomia_id:
            raise ValueError(
                f"taxonomia_id {data.taxonomia_id} does not match "
                f"modus_operandi {data.modus_operandi_id}'s parent "
                f"taxonomia {modus_operandi.taxonomia_id}"
            )

        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="ingest_yellow_flag",
        )
        embedding = uow.embed([data.text])
        document = YellowFlagDocument(
            id=uuid4(),
            text=data.text,
            text_embedded=embedding.vectors[0],
            segmento=data.segmento,
            configuration=data.configuration,
            version=data.version,
            modus_operandi_id=data.modus_operandi_id,
            taxonomia_id=data.taxonomia_id,
            activate=data.activate,
        )
        created = self._repository.create(document)

        self._repository.update(
            replace(
                modus_operandi,
                yellow_flags=[*modus_operandi.yellow_flags, created.id],
            )
        )
        return created
