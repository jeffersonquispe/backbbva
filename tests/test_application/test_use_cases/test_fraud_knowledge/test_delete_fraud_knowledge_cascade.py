from __future__ import annotations

import uuid

import pytest

from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeDocument,
    ModusOperandiDocument,
    RedFlagDocument,
    SimilarCaseDocument,
    TaxonomiaDocument,
    YellowFlagDocument,
)
from src.application.use_cases.fraud_knowledge.delete_modus_operandi import (
    DeleteModusOperandiUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_red_flag import (
    DeleteRedFlagUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_similar_case import (
    DeleteSimilarCaseUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_taxonomia import (
    DeleteTaxonomiaUseCase,
)
from src.application.use_cases.fraud_knowledge.delete_yellow_flag import (
    DeleteYellowFlagUseCase,
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
        channel: str | None = None,
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
    RedFlagDocument,
    YellowFlagDocument,
]:
    taxonomia = repository.create(
        TaxonomiaDocument(
            id=uuid.uuid4(),
            text="taxonomia",
            text_embedded=[0.1],
            segmento="tarjetas",
            configuration="default",
            version=1,
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
            segmento="tarjetas",
            configuration="default",
            version=1,
            taxonomia_id=taxonomia.id,
            taxonomia=taxonomia.text,
            similar_cases=[similar_case_id],
            red_flags=[red_flag_id],
            yellow_flags=[yellow_flag_id],
        )
    )
    similar_case = repository.create(
        SimilarCaseDocument(
            id=similar_case_id,
            text="caso similar",
            text_embedded=[0.1],
            segmento="tarjetas",
            configuration="default",
            version=1,
            modus_operandi_id=modus_operandi.id,
            taxonomia_id=taxonomia.id,
        )
    )
    red_flag = repository.create(
        RedFlagDocument(
            id=red_flag_id,
            text="alerta roja",
            text_embedded=[0.1],
            segmento="tarjetas",
            configuration="default",
            version=1,
            modus_operandi_id=modus_operandi.id,
            taxonomia_id=taxonomia.id,
        )
    )
    yellow_flag = repository.create(
        YellowFlagDocument(
            id=yellow_flag_id,
            text="alerta amarilla",
            text_embedded=[0.1],
            segmento="tarjetas",
            configuration="default",
            version=1,
            modus_operandi_id=modus_operandi.id,
            taxonomia_id=taxonomia.id,
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


def test_delete_red_flag_removes_id_from_parent() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    _, modus_operandi, _, red_flag, _ = _seed_full_tree(repository)

    DeleteRedFlagUseCase(repository).execute(red_flag.id)

    assert repository.get(red_flag.id) is None
    updated_parent = repository.get(modus_operandi.id)
    assert isinstance(updated_parent, ModusOperandiDocument)
    assert updated_parent.red_flags == []


def test_delete_yellow_flag_removes_id_from_parent() -> None:
    repository = InMemoryFraudKnowledgeRepository()
    _, modus_operandi, _, _, yellow_flag = _seed_full_tree(repository)

    DeleteYellowFlagUseCase(repository).execute(yellow_flag.id)

    assert repository.get(yellow_flag.id) is None
    updated_parent = repository.get(modus_operandi.id)
    assert isinstance(updated_parent, ModusOperandiDocument)
    assert updated_parent.yellow_flags == []


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
