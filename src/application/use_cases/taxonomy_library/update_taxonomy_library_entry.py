from __future__ import annotations

from src.application.ports.embedding_port import EmbeddingUnitOfWorkFactory
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.taxonomy_library_port import (
    TaxonomyLibraryEntry,
    TaxonomyLibraryRepository,
)
from src.application.use_cases.taxonomy_library.create_taxonomy_library_entry import (
    embedding_text,
)


class TaxonomyLibraryEntryNotFoundError(Exception):
    pass


class UpdateTaxonomyLibraryEntryUseCase:
    def __init__(
        self,
        taxonomy_library_repository: TaxonomyLibraryRepository,
        embedding_unit_of_work_factory: EmbeddingUnitOfWorkFactory,
        monitoring: MonitoringPort,
        embedding_model: str,
    ) -> None:
        self._entries = taxonomy_library_repository
        self._embedding_unit_of_work_factory = embedding_unit_of_work_factory
        self._monitoring = monitoring
        self._embedding_model = embedding_model

    def execute(
        self,
        entry_id: str,
        *,
        code: str | None = None,
        name: str | None = None,
        description: str | None = None,
        variables: list[str] | None = None,
        examples: list[str] | None = None,
        active: bool | None = None,
    ) -> TaxonomyLibraryEntry:
        current = self._entries.get(entry_id)
        if current is None:
            raise TaxonomyLibraryEntryNotFoundError(f"Taxonomy library entry not found: {entry_id}")

        embedding: list[float] | None = None
        text_changed = (
            (name is not None and name != current.name)
            or (description is not None and description != current.description)
            or (examples is not None and examples != current.examples)
        )
        if text_changed:
            uow = self._embedding_unit_of_work_factory.create(
                model=self._embedding_model,
                monitoring=self._monitoring,
                operation_name="embed_taxonomy_library_entry",
            )
            embedding = uow.embed(
                [
                    embedding_text(
                        name=name if name is not None else current.name,
                        description=description if description is not None else current.description,
                        examples=examples if examples is not None else current.examples,
                    )
                ]
            ).vectors[0]

        updated = self._entries.update(
            entry_id,
            code=code,
            name=name,
            description=description,
            variables=variables,
            examples=examples,
            active=active,
            embedding=embedding,
        )
        if updated is None:
            raise TaxonomyLibraryEntryNotFoundError(f"Taxonomy library entry not found: {entry_id}")
        return updated
