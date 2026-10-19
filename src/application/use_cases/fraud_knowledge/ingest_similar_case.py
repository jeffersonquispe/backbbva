from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    ModusOperandiDocument,
    SimilarCaseDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.runtime_defaults import DEFAULT_ID_GENERATOR


@dataclass(frozen=True)
class IngestSimilarCaseInput:
    text: str
    vector_store_id: str
    vector_store_version: int
    modus_operandi_id: UUID
    taxonomia_id: UUID
    # See IngestTaxonomiaInput.text_embedded - same recycle-if-possible rule.
    text_embedded: list[float] | None = None


class IngestSimilarCaseUseCase:
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

    def execute(self, data: IngestSimilarCaseInput) -> SimilarCaseDocument:
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

        text_embedded = data.text_embedded
        if text_embedded is None:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="ingest_similar_case",
            )
            text_embedded = uow.embed([data.text]).vectors[0]
        document = SimilarCaseDocument(
            id=self._id_generator.new_id(),
            text=data.text,
            text_embedded=text_embedded,
            vector_store_id=data.vector_store_id,
            vector_store_version=data.vector_store_version,
            modus_operandi_id=data.modus_operandi_id,
            taxonomia_id=data.taxonomia_id,
        )
        created = self._repository.create(document)
        assert isinstance(created, SimilarCaseDocument)

        self._repository.update(
            replace(
                modus_operandi,
                similar_cases=[*modus_operandi.similar_cases, created.id],
            )
        )
        return created
