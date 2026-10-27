from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from src.application.ports.agent_session_port import AgentSessionStatus
from src.application.ports.clock_port import Clock
from src.application.use_cases.vector_store_instances.cleanup_vector_store_generations import (
    CleanupVectorStoreGenerationsUseCase,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.configurations.entities import SegmentSettings
from src.domain.fraud_knowledge.vector_store_generations import (
    VectorStoreGeneration,
    VectorStoreGenerationStatus,
)

NOW = datetime(2026, 10, 27, tzinfo=UTC)


class FixedClock(Clock):
    def now(self):
        return NOW


class InMemoryGenerations:
    def __init__(self, records):
        self.items = {(g.instance_id, g.generation): g for g in records}

    def list(self, instance_id=None):
        return [g for g in self.items.values() if instance_id in (None, g.instance_id)]

    def update(self, record):
        self.items[record.instance_id, record.generation] = record
        return record


class InMemoryConfigurations:
    """Mirrors the Dynamo repository: list_all_versions() rows carry no
    segments, so pins are only visible through list_vector_store_pins()."""

    def __init__(self, records):
        self.records = records

    def list_all_versions(self):
        return [replace_segments(record) for record in self.records]

    def list_vector_store_pins(self):
        from src.domain.fraud_knowledge.vector_store_generations import (
            configuration_vector_store_pins,
        )

        return {
            (record.configuration_id, record.version): configuration_vector_store_pins(record)
            for record in self.records
        }


def replace_segments(record):
    return SimpleNamespace(**{**vars(record), "segments": {}})


class InMemoryListRepository:
    def __init__(self, items=()):
        self.items = items

    def list(self):
        return list(self.items)

    def list_releases(self, limit=200, statuses=None):
        return [r for r in self.items if r.status in statuses]

    def list_by_status(self, status, limit=None):
        return [r for r in self.items if r.status == status]

    def load_tree(self, session_id):
        return self.items.get(session_id) if isinstance(self.items, dict) else None


class RecordingKnowledgeRepository:
    def __init__(self):
        self.deleted = []

    def delete_generation(self, instance, generation):
        self.deleted.append((instance, generation))
        return 4


def _generation(number, *, days=30, status=VectorStoreGenerationStatus.READY):
    return VectorStoreGeneration(instance_id="vs", generation=number, status=status,
        built_by="tester", created_at=NOW-timedelta(days=days))


def _config(number, generation, *, active=False, used=False):
    segment = SegmentSettings(enabled=True)
    research = segment.agent.detector.delegated_research.vector_store
    research.enabled = True
    research.vector_store_instance_id = "vs"
    research.vector_store_generation = generation
    return SimpleNamespace(configuration_id="cfg", version=number, active=active,
        ever_activated=used, activated_at=NOW-timedelta(days=10-number),
        created_at=NOW-timedelta(days=10-number), segments={"one": segment})


def _use_case(generations, configs=(), requests=(), runs=(), releases=(), sessions=(), trees=()):
    repository = InMemoryGenerations(generations)
    knowledge = RecordingKnowledgeRepository()
    use_case = CleanupVectorStoreGenerationsUseCase(
        generations=repository, configurations=InMemoryConfigurations(configs),
        deploy_requests=InMemoryListRepository(requests), test_runs=InMemoryListRepository(runs),
        releases=InMemoryListRepository(releases), sessions=InMemoryListRepository(sessions),
        optimization_runs=InMemoryListRepository(trees), fraud_knowledge_repository=knowledge,
        clock=FixedClock(),
    )
    return use_case, repository, knowledge


@given(st.integers(min_value=1, max_value=30), st.sets(st.integers(31, 100), max_size=15))
def test_cleanup_never_retires_an_active_configuration_pin(protected, unprotected):
    use_case, repo, knowledge = _use_case([_generation(n) for n in [protected, *unprotected]],
        [_config(1, protected, active=True)])
    use_case.execute(retention_days=14, rollback_configurations=2)
    assert repo.items["vs", protected].status == VectorStoreGenerationStatus.READY
    assert ("vs", protected) not in knowledge.deleted
    assert set(knowledge.deleted) == {("vs", n) for n in unprotected}


def test_retention_protects_rollback_pending_deploy_test_and_open_optimizer_pins():
    configs = [_config(1, 1, used=True), _config(2, 2, used=True), _config(3, 3, active=True),
               _config(4, 4), _config(5, 5)]
    requests = [SimpleNamespace(status="pending", target_configuration_id="cfg", target_version=4)]
    runs = [SimpleNamespace(status="RUNNING", config=SimpleNamespace(configuration_ref=
        SimpleNamespace(configuration_id="cfg", version=5)))]
    pin = ComponentVersionReference("vector_store", "vs", "6", "a"*64)
    candidate_pin = replace(pin, version="7")
    sessions = [SimpleNamespace(session_id="s", status=AgentSessionStatus.PAUSED,
        baseline_components=(pin,))]
    experiment = SimpleNamespace(components=(candidate_pin,), baseline_components=())
    tree = SimpleNamespace(root=SimpleNamespace(baseline_components=(), winning_components=()),
        candidates=(SimpleNamespace(experiments=(SimpleNamespace(experiment=experiment),)),), unassigned_experiments=())
    release = SimpleNamespace(status="PENDING_APPROVAL", candidate_component_pins=(replace(pin, version="8"),), previous_component_pins=())
    use_case, repo, knowledge = _use_case([_generation(n) for n in range(1, 10)], configs,
        requests, runs, [release], sessions, {"s": tree})
    output = use_case.execute(retention_days=14, rollback_configurations=2)
    assert knowledge.deleted == [("vs", 9)]
    assert output.retired == ("vs@g9",)
    assert output.protected == 8
    use_case.execute(retention_days=14, rollback_configurations=2)
    assert knowledge.deleted == [("vs", 9)]


def test_dry_run_never_writes_and_recent_generation_is_kept():
    use_case, repo, knowledge = _use_case([_generation(1), _generation(2, days=1)])
    output = use_case.execute(retention_days=14, rollback_configurations=2, dry_run=True)
    assert output.retired == ("vs@g1",)
    assert output.protected == 1
    assert knowledge.deleted == []
    assert repo.items["vs", 1].status == VectorStoreGenerationStatus.READY


def test_stale_build_and_failed_partial_writes_are_cleaned_without_affecting_ready():
    use_case, repo, knowledge = _use_case([
        _generation(1, status=VectorStoreGenerationStatus.BUILDING),
        _generation(2, status=VectorStoreGenerationStatus.FAILED),
        _generation(3, days=0),
    ])
    output = use_case.execute(retention_days=14, rollback_configurations=2)
    assert output.failed_stale_builds == ("vs@g1",)
    assert repo.items["vs", 1].status == VectorStoreGenerationStatus.FAILED
    assert repo.items["vs", 3].status == VectorStoreGenerationStatus.READY
    assert knowledge.deleted == [("vs", 1), ("vs", 2)]


def test_instance_scope_retires_only_that_instance_with_zero_retention():
    other = replace(_generation(1, days=0), instance_id="other")
    use_case, repo, knowledge = _use_case([_generation(1, days=0), other])
    output = use_case.execute(
        retention_days=0, rollback_configurations=2, instance_id="vs"
    )
    assert output.retired == ("vs@g1",)
    assert knowledge.deleted == [("vs", 1)]
    assert repo.items["other", 1].status == VectorStoreGenerationStatus.READY
