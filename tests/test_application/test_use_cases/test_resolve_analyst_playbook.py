from __future__ import annotations

import uuid
from datetime import datetime, timezone

from src.application.ports.configuration_port import AnalystPlaybook
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    ModusOperandiDocument,
    SearchPipeline,
)
from src.application.ports.vector_store_instance_port import VectorStoreInstance
from src.application.use_cases.alerts.resolve_analyst_playbook import (
    ResolveAnalystPlaybookUseCase,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)


class InMemoryVectorStoreInstanceRepository:
    def __init__(self, instances: list[VectorStoreInstance]) -> None:
        self._instances = {instance.id: instance for instance in instances}

    def create(self, instance, assets):
        raise NotImplementedError

    def list(self):
        return list(self._instances.values())

    def get(self, instance_id: str) -> VectorStoreInstance | None:
        return self._instances.get(instance_id)

    def update(self, instance):
        raise NotImplementedError

    def list_assets(self, instance_id: str):
        raise NotImplementedError

    def add_asset(self, asset):
        raise NotImplementedError

    def remove_asset(self, instance_id, relation_id) -> None:
        raise NotImplementedError


def _promoted_instance(instance_id: str = "vs-1", version: int = 1) -> VectorStoreInstance:
    return VectorStoreInstance(
        id=instance_id,
        version=1,
        name="Instancia",
        description="",
        created_at=datetime.now(timezone.utc),
        created_by="tester",
        promoted_version=version,
    )


class ScriptedFraudKnowledgeSearchPort(FraudKnowledgeSearchPort):
    def __init__(self, results: list[FraudKnowledgeSearchResult]) -> None:
        self._results = results
        self.calls: list[dict] = []

    def search(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        vector_store_id: str,
        vector_store_version: int,
        document_type: DocumentType,
        top_k: int = 5,
    ) -> list[FraudKnowledgeSearchResult]:
        self.calls.append(
            {
                "query": query,
                "pipeline": pipeline,
                "vector_store_id": vector_store_id,
                "vector_store_version": vector_store_version,
                "document_type": document_type,
                "top_k": top_k,
            }
        )
        return self._results


def _mo_document(library_id: str, score: float) -> FraudKnowledgeSearchResult:
    return FraudKnowledgeSearchResult(
        document=ModusOperandiDocument(
            id=uuid.uuid4(),
            text="patron",
            text_embedded=[0.1],
            vector_store_id="vs-1",
            vector_store_version=1,
            taxonomia_id=uuid.uuid4(),
            taxonomia="Suplantación",
            similar_cases=[],
            flags=[],
            library_id=library_id,
        ),
        score=score,
    )


def _use_case(results: list[FraudKnowledgeSearchResult]) -> tuple[
    ResolveAnalystPlaybookUseCase, ScriptedFraudKnowledgeSearchPort
]:
    search_port = ScriptedFraudKnowledgeSearchPort(results)
    search_use_case = SearchFraudKnowledgeUseCase(
        search_port, InMemoryVectorStoreInstanceRepository([_promoted_instance("vs-1", version=2)])
    )
    return ResolveAnalystPlaybookUseCase(search_use_case), search_port


def test_resolves_playbook_matching_the_top_hit() -> None:
    playbook = AnalystPlaybook(id="pb-1", name="Vishing", modus_operandi_id="mo-1")
    use_case, search_port = _use_case([_mo_document("mo-1", score=0.9)])

    resolved = use_case.execute(
        "cambio de dispositivo", vector_store_instance_id="vs-1", playbooks=[playbook]
    )

    assert resolved == playbook
    assert search_port.calls == [
        {
            "query": "cambio de dispositivo",
            "pipeline": SearchPipeline.BALANCED,
            "vector_store_id": "vs-1",
            "vector_store_version": 2,
            "document_type": DocumentType.MODUS_OPERANDI,
            "top_k": 5,
        }
    ]


def test_resolves_playbook_matching_a_lower_ranked_hit() -> None:
    # The closest match's modus operandi has no playbook yet - keeps
    # checking further down the ranked results rather than giving up at #1.
    playbook = AnalystPlaybook(id="pb-2", name="Phishing", modus_operandi_id="mo-2")
    use_case, _ = _use_case(
        [_mo_document("mo-1", score=0.9), _mo_document("mo-2", score=0.7)]
    )

    resolved = use_case.execute(
        "correo sospechoso", vector_store_instance_id="vs-1", playbooks=[playbook]
    )

    assert resolved == playbook


def test_returns_none_when_no_playbook_has_a_modus_operandi_id() -> None:
    playbook = AnalystPlaybook(id="pb-1", name="Generico")
    use_case, search_port = _use_case([_mo_document("mo-1", score=0.9)])

    resolved = use_case.execute(
        "query", vector_store_instance_id="vs-1", playbooks=[playbook]
    )

    assert resolved is None
    # Never even searches - nothing configured could match.
    assert search_port.calls == []


def test_returns_none_without_a_vector_store_instance_id() -> None:
    playbook = AnalystPlaybook(id="pb-1", name="Vishing", modus_operandi_id="mo-1")
    use_case, search_port = _use_case([_mo_document("mo-1", score=0.9)])

    resolved = use_case.execute("query", vector_store_instance_id=None, playbooks=[playbook])

    assert resolved is None
    assert search_port.calls == []


def test_returns_none_when_no_hit_matches_any_configured_playbook() -> None:
    playbook = AnalystPlaybook(id="pb-1", name="Vishing", modus_operandi_id="mo-1")
    use_case, _ = _use_case([_mo_document("mo-999", score=0.9)])

    resolved = use_case.execute(
        "query", vector_store_instance_id="vs-1", playbooks=[playbook]
    )

    assert resolved is None


def test_fails_open_when_vector_store_not_promoted() -> None:
    playbook = AnalystPlaybook(id="pb-1", name="Vishing", modus_operandi_id="mo-1")
    search_port = ScriptedFraudKnowledgeSearchPort([_mo_document("mo-1", score=0.9)])
    search_use_case = SearchFraudKnowledgeUseCase(
        search_port, InMemoryVectorStoreInstanceRepository([])
    )
    use_case = ResolveAnalystPlaybookUseCase(search_use_case)

    resolved = use_case.execute(
        "query", vector_store_instance_id="vs-missing", playbooks=[playbook]
    )

    assert resolved is None
    assert search_port.calls == []
