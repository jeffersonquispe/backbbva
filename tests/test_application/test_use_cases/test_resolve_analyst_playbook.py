from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.configuration_port import ResolutionTag, ShortageBehavior
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    FraudKnowledgeSearchPort,
    FraudKnowledgeSearchResult,
    ModusOperandiDocument,
    SearchPipeline,
)
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryEntry,
    ModusOperandiPlaybook,
)
from src.application.ports.vector_store_instance_port import VectorStoreInstance
from src.application.use_cases.alerts.resolve_analyst_playbook import (
    ResolveAnalystPlaybookUseCase,
    ResolvedPlaybook,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)


class InMemoryModusOperandiLibraryRepository:
    def __init__(self, entries: list[ModusOperandiLibraryEntry]) -> None:
        self._entries = {entry.id: entry for entry in entries}

    def get(self, entry_id: str) -> ModusOperandiLibraryEntry | None:
        return self._entries.get(entry_id)


_VOICEBOT_PLAYBOOK = ModusOperandiPlaybook(
    strategy="confirmar con el cliente",
    resolution=ShortageBehavior(resolution_tag=ResolutionTag.SEND_TO_VOICEBOT),
    if_no_voicebot=ShortageBehavior(resolution_tag=ResolutionTag.SCALE_TO_ANALYST),
)


def _entry(
    entry_id: str,
    playbook: ModusOperandiPlaybook | None = _VOICEBOT_PLAYBOOK,
    active: bool = True,
) -> ModusOperandiLibraryEntry:
    now = datetime.now(UTC)
    return ModusOperandiLibraryEntry(
        id=entry_id,
        title=f"MO {entry_id}",
        narrative="patron",
        taxonomy_library_id="tx-1",
        created_at=now,
        updated_at=now,
        active=active,
        playbook=playbook,
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
        created_at=datetime.now(UTC),
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


def _use_case(
    results: list[FraudKnowledgeSearchResult],
    entries: list[ModusOperandiLibraryEntry],
) -> tuple[ResolveAnalystPlaybookUseCase, ScriptedFraudKnowledgeSearchPort]:
    search_port = ScriptedFraudKnowledgeSearchPort(results)
    search_use_case = SearchFraudKnowledgeUseCase(
        search_port, InMemoryVectorStoreInstanceRepository([_promoted_instance("vs-1", version=2)])
    )
    return (
        ResolveAnalystPlaybookUseCase(
            search_use_case, InMemoryModusOperandiLibraryRepository(entries)
        ),
        search_port,
    )


def test_resolves_the_library_playbook_of_the_top_hit() -> None:
    use_case, search_port = _use_case(
        [_mo_document("mo-1", score=0.9)], [_entry("mo-1")]
    )

    resolved = use_case.execute("cambio de dispositivo", vector_store_instance_id="vs-1")

    assert resolved == ResolvedPlaybook(
        modus_operandi_id="mo-1",
        modus_operandi_title="MO mo-1",
        playbook=_VOICEBOT_PLAYBOOK,
    )
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


def test_skips_hits_whose_modus_operandi_has_no_playbook_or_is_inactive() -> None:
    # The closest matches have no usable playbook - keeps checking further
    # down the ranked results rather than giving up at #1.
    use_case, _ = _use_case(
        [
            _mo_document("mo-1", score=0.9),
            _mo_document("mo-2", score=0.8),
            _mo_document("mo-3", score=0.7),
        ],
        [_entry("mo-1", playbook=None), _entry("mo-2", active=False), _entry("mo-3")],
    )

    resolved = use_case.execute("correo sospechoso", vector_store_instance_id="vs-1")

    assert resolved is not None
    assert resolved.modus_operandi_id == "mo-3"


def test_returns_none_without_a_vector_store_instance_id() -> None:
    use_case, search_port = _use_case([_mo_document("mo-1", score=0.9)], [_entry("mo-1")])

    resolved = use_case.execute("query", vector_store_instance_id=None)

    assert resolved is None
    assert search_port.calls == []


def test_returns_none_when_no_hit_has_a_library_entry() -> None:
    use_case, _ = _use_case([_mo_document("mo-999", score=0.9)], [_entry("mo-1")])

    assert use_case.execute("query", vector_store_instance_id="vs-1") is None


def test_fails_open_when_vector_store_not_promoted() -> None:
    search_port = ScriptedFraudKnowledgeSearchPort([_mo_document("mo-1", score=0.9)])
    search_use_case = SearchFraudKnowledgeUseCase(
        search_port, InMemoryVectorStoreInstanceRepository([])
    )
    use_case = ResolveAnalystPlaybookUseCase(
        search_use_case, InMemoryModusOperandiLibraryRepository([_entry("mo-1")])
    )

    resolved = use_case.execute("query", vector_store_instance_id="vs-missing")

    assert resolved is None
    assert search_port.calls == []
