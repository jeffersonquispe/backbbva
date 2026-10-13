from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FlagDocument,
    ModusOperandiDocument,
)
from src.application.ports.fraud_knowledge_repository_port import (
    FraudKnowledgeRepository,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.runtime_defaults import DEFAULT_ID_GENERATOR


@dataclass(frozen=True)
class IngestFlagInput:
    text: str
    flag_type: DocumentType  # RED_FLAG | YELLOW_FLAG
    vector_store_id: str
    vector_store_version: int
    modus_operandi_ids: list[UUID]
    # See IngestTaxonomiaInput.text_embedded - same recycle-if-possible rule.
    text_embedded: list[float] | None = None


class IngestFlagUseCase:
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

    def execute(self, data: IngestFlagInput) -> FlagDocument:
        parents: list[ModusOperandiDocument] = []
        for modus_operandi_id in data.modus_operandi_ids:
            parent = self._repository.get(modus_operandi_id)
            if parent is None or parent.type != DocumentType.MODUS_OPERANDI:
                raise ValueError(f"modus_operandi {modus_operandi_id} does not exist")
            assert isinstance(parent, ModusOperandiDocument)
            parents.append(parent)

        text_embedded = data.text_embedded
        if text_embedded is None:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="ingest_flag",
            )
            text_embedded = uow.embed([data.text]).vectors[0]
        document = FlagDocument(
            id=self._id_generator.new_id(),
            text=data.text,
            text_embedded=text_embedded,
            vector_store_id=data.vector_store_id,
            vector_store_version=data.vector_store_version,
            modus_operandi_ids=data.modus_operandi_ids,
            type=data.flag_type,
        )
        created = self._repository.create(document)

        for parent in parents:
            self._repository.update(replace(parent, flags=[*parent.flags, created.id]))

        return created
