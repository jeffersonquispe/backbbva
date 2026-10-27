from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    VectorStoreGenerationUnavailableError,
)
from src.application.use_cases.vector_store_instances.pin_configuration_vector_stores import (
    PinConfigurationVectorStoresUseCase,
)
from src.domain.configurations.entities import SegmentSettings
from src.domain.fraud_knowledge.vector_store_generations import (
    VectorStoreGeneration,
    VectorStoreGenerationStatus,
)


def _segment(generation=None):
    segment = SegmentSettings(enabled=True)
    for step in (segment.agent.detector, segment.agent.classification):
        research = step.delegated_research.vector_store
        research.enabled = True
        research.vector_store_instance_id = "vs"
        research.vector_store_generation = generation
    return segment


class RecordingBuild:
    def __init__(self, record: VectorStoreGeneration) -> None:
        self._record = record
        self.calls: list[tuple[str, str]] = []

    def execute(self, instance_id: str, *, actor: str):
        self.calls.append((instance_id, actor))
        return SimpleNamespace(generation=self._record)


class InMemoryGenerationRepository:
    def __init__(self, record: VectorStoreGeneration) -> None:
        self._record = record
        self.gets: list[tuple[str, int]] = []

    def get(self, instance_id: str, generation: int):
        self.gets.append((instance_id, generation))
        if (instance_id, generation) == (self._record.instance_id, self._record.generation):
            return self._record
        return None

    def list(self, instance_id=None):
        return [self._record]


def _use_case(status=VectorStoreGenerationStatus.READY):
    record = VectorStoreGeneration("vs", 7, status, "qa", datetime.now(UTC))
    build, generations = RecordingBuild(record), InMemoryGenerationRepository(record)
    return PinConfigurationVectorStoresUseCase(build, generations), build, generations


def test_saving_builds_shared_instance_once_and_does_not_mutate_input():
    use_case, build, _ = _use_case()
    original = {"segment": _segment()}
    pinned = use_case.execute(original, actor="analyst")
    assert build.calls == [("vs", "analyst")]
    assert pinned["segment"].agent.detector.delegated_research.vector_store.vector_store_generation == 7
    assert pinned["segment"].agent.classification.delegated_research.vector_store.vector_store_generation == 7
    assert original["segment"].agent.detector.delegated_research.vector_store.vector_store_generation is None


def test_explicit_ready_generation_is_preserved_without_building_latest():
    use_case, build, generations = _use_case()
    pinned = use_case.execute({"segment": _segment(7)}, actor="analyst")
    assert build.calls == []
    assert generations.gets[-1] == ("vs", 7)
    assert pinned["segment"].agent.detector.delegated_research.vector_store.vector_store_generation == 7


@pytest.mark.parametrize("status", [VectorStoreGenerationStatus.RETIRED,
    VectorStoreGenerationStatus.FAILED, VectorStoreGenerationStatus.BUILDING])
def test_saving_and_verifying_reject_unavailable_pins(status):
    use_case, build, _ = _use_case(status)
    segments = {"segment": _segment(7)}
    with pytest.raises(VectorStoreGenerationUnavailableError, match="not available"):
        use_case.execute(segments, actor="analyst")
    with pytest.raises(VectorStoreGenerationUnavailableError, match="not available"):
        use_case.verify(SimpleNamespace(segments=segments))
    assert build.calls == []


def test_legacy_unpinned_tool_must_be_saved_before_test_or_activation():
    use_case, _, _ = _use_case()
    configuration = SimpleNamespace(segments={"segment": _segment()},
        configuration_id="cfg", version=1)
    with pytest.raises(VectorStoreGenerationUnavailableError, match="save the configuration again"):
        use_case.verify(configuration)
