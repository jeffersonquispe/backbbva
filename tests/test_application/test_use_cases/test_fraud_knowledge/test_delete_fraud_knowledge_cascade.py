from __future__ import annotations

import uuid

import pytest

from dataclasses import replace

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FlagDocument,
    FraudKnowledgeDocument,
    ModusOperandiDocument,
    SimilarCaseDocument,
    TaxonomiaDocument,
)
from src.application.use_cases.fraud_knowledge.delete_flag import DeleteFlagUseCase
from src.application.use_cases.fraud_knowledge.delete_modus_operandi import (
    DeleteModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_similar_case import (
    DeleteSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_taxonomia import (
    DeleteTaxonomiaUseCase,
)


class InMemoryFraudKnowledgeRepository:
    def __init__(self) -> None:
        self._documents: dict[uuid.UUID, FraudKnowledgeDocument] = {}

    def create(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def get(self, document_id: uuid.UUID) -> FraudKnowledgeDocument | None:
        return self._documents.get(document_id)

    def update(self, document: FraudKnowledgeDocument) -> FraudKnowledgeDocument:
        self._documents[document.id] = document
        return document

    def delete(self, document_id: uuid.UUID) -> None:
        self._documents.pop(document_id, None)

    def list(
        self,
        document_type: DocumentType | None = None,
        *,
        vector_store_id: str | None = None,
        vector_store_version: int | None = None,
    ) -> list[FraudKnowledgeDocument]:
        results = list(self._documents.values())
        if document_type is not None:
            results = [d for d in results if d.type == document_type]
        return results


def _seed_full_tree(
    repository: InMemoryFraudKnowledgeRepository,
) -> tuple[
    TaxonomiaDocument,
    ModusOperandiDocument,
    SimilarCaseDocument,
    FlagDocument,
    FlagDocument,
]:
    taxonomia = repository.create(
        TaxonomiaDocument(
            id=uuid.uuid4(),
            text="taxonomia",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
        )
    )
    similar_case_id = uuid.uuid4()
    red_flag_id = uuid.uuid4()
    yellow_flag_id = uuid.uuid4()
    modus_operandi = repository.create(
        ModusOperandiDocument(
            id=uuid.uuid4(),
            text="modus operandi",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=taxonomia.id,
            taxonomia=taxonomia.text,
            similar_cases=[similar_case_id],
            flags=[red_flag_id, yellow_flag_id],
        )
    )
    similar_case = repository.create(
        SimilarCaseDocument(
            id=similar_case_id,
            text="caso similar",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
            modus_operandi_id=modus_operandi.id,
            taxonomia_id=taxonomia.id,
        )
    )
    red_flag = repository.create(
        FlagDocument(
            id=red_flag_id,
            text="alerta roja",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
            modus_operandi_ids=[modus_operandi.id],
            type=DocumentType.RED_FLAG,
        )
    )
    yellow_flag = repository.create(
        FlagDocument(
            id=yellow_flag_id,
            text="alerta amarilla",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
            modus_operandi_ids=[modus_operandi.id],
            type=DocumentType.YELLOW_FLAG,
        )
    )
    return taxonomia, modus_operandi, similar_case, red_flag, yellow_flag


def test_delete_similar_case_removes_id_from_parent() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    _, modus_operandi, similar_case, _, _ = _seed_full_tree(repository)

    DeleteSimilarCaseUseCase(repository).execute(similar_case.id)

    assert repository.get(similar_case.id) is None
    updated_parent = repository.get(modus_operandi.id)
    assert isinstance(updated_parent, ModusOperandiDocument)
    assert updated_parent.similar_cases == []


def test_delete_flag_removes_id_from_parent() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    _, modus_operandi, _, red_flag, yellow_flag = _seed_full_tree(repository)

    DeleteFlagUseCase(repository).execute(red_flag.id)

    assert repository.get(red_flag.id) is None
    updated_parent = repository.get(modus_operandi.id)
    assert isinstance(updated_parent, ModusOperandiDocument)
    assert updated_parent.flags == [yellow_flag.id]


def test_delete_flag_removes_id_from_all_parents_when_many_to_many() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    _, mo_a, _, flag, _ = _seed_full_tree(repository)
    mo_b = repository.create(
        ModusOperandiDocument(
            id=uuid.uuid4(),
            text="modus operandi B",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=mo_a.taxonomia_id,
            taxonomia=mo_a.taxonomia,
            similar_cases=[],
            flags=[flag.id],
        )
    )
    repository.update(replace(flag, modus_operandi_ids=[mo_a.id, mo_b.id]))

    DeleteFlagUseCase(repository).execute(flag.id)

    assert repository.get(flag.id) is None
    updated_a = repository.get(mo_a.id)
    updated_b = repository.get(mo_b.id)
    assert isinstance(updated_a, ModusOperandiDocument)
    assert isinstance(updated_b, ModusOperandiDocument)
    assert flag.id not in updated_a.flags
    assert updated_b.flags == []


def test_delete_modus_operandi_detaches_shared_flag_but_keeps_it_alive() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    _, mo_a, _, flag, _ = _seed_full_tree(repository)
    mo_b = repository.create(
        ModusOperandiDocument(
            id=uuid.uuid4(),
            text="modus operandi B",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=mo_a.taxonomia_id,
            taxonomia=mo_a.taxonomia,
            similar_cases=[],
            flags=[flag.id],
        )
    )
    repository.update(replace(flag, modus_operandi_ids=[mo_a.id, mo_b.id]))

    # Deleting mo_a must leave the shared flag alive, now only linked to mo_b.
    DeleteModusOperandiUseCase(repository).execute(mo_a.id)
    still_alive = repository.get(flag.id)
    assert still_alive is not None
    assert isinstance(still_alive, FlagDocument)
    assert still_alive.modus_operandi_ids == [mo_b.id]

    # Deleting mo_b next must now delete the orphaned flag.
    DeleteModusOperandiUseCase(repository).execute(mo_b.id)
    assert repository.get(flag.id) is None


def test_delete_modus_operandi_cascades_to_all_children() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    _, modus_operandi, similar_case, red_flag, yellow_flag = _seed_full_tree(repository)

    DeleteModusOperandiUseCase(repository).execute(modus_operandi.id)

    assert repository.get(modus_operandi.id) is None
    assert repository.get(similar_case.id) is None
    assert repository.get(red_flag.id) is None
    assert repository.get(yellow_flag.id) is None


def test_delete_taxonomia_cascades_through_modus_operandi_and_children() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    taxonomia, modus_operandi, similar_case, red_flag, yellow_flag = _seed_full_tree(
        repository
    )

    DeleteTaxonomiaUseCase(repository).execute(taxonomia.id)

    assert repository.get(taxonomia.id) is None
    assert repository.get(modus_operandi.id) is None
    assert repository.get(similar_case.id) is None
    assert repository.get(red_flag.id) is None
    assert repository.get(yellow_flag.id) is None


def test_delete_taxonomia_raises_when_not_found() -> None:
    repository = InMemoryFraudKnowledgeRepository()

    with pytest.raises(ValueError):
        DeleteTaxonomiaUseCase(repository).execute(uuid.uuid4())
