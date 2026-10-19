from __future__ import annotations

from src.application.ports.clock_port import Clock
from src.application.ports.embedding_unit_of_work_factory_port import (
    EmbeddingUnitOfWorkFactory,
)
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.taxonomy_library_port import (
    TaxonomyLibraryRepository,
)
from src.application.runtime_defaults import (
    DEFAULT_ID_GENERATOR,
    resolve_clock,
)
from src.domain.fraud_knowledge.library_entities import TaxonomyLibraryEntry


def embedding_text(*, name: str, description: str, examples: list[str]) -> str:
    text = f"{name}: {description}"
    if examples:
        text += ". Ejemplos: " + "; ".join(examples)
    return text


class CreateTaxonomyLibraryEntryUseCase:
    def __init__(
        self,
        taxonomy_library_repository: TaxonomyLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._entries = taxonomy_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def execute(
        self,
        code: str,
        name: str,
        description: str = "",
        variables: list[str] | None = None,
        examples: list[str] | None = None,
    ) -> TaxonomyLibraryEntry:
        normalized_name = " ".join(name.split()).casefold()
        for existing in self._entries.list():
            if " ".join(existing.name.split()).casefold() == normalized_name:
                return existing
        now = self._clock.now()
        examples = examples or []
        uow = self._embedding_unit_of_work_factory.create(
            model=self._embedding_model,
            monitoring=self._monitoring,
            operation_name="embed_taxonomy_library_entry",
        )
        embedding = uow.embed(
            [embedding_text(name=name, description=description, examples=examples)]
        ).vectors[0]
        return self._entries.create(
            TaxonomyLibraryEntry(
                id=str(self._id_generator.new_id()),
                code=code,
                name=name,
                description=description,
                variables=variables or [],
                examples=examples,
                created_at=now,
                updated_at=now,
                embedding=embedding,
            )
        )
