from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime

from src.application.ports.vector_store_instance_port import VectorStoreInstance
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.configurations.entities import default_segments
from src.domain.fraud_knowledge.vector_store_generations import (
    VectorStoreGeneration,
    VectorStoreGenerationStatus,
    VectorStoreManifestItem,
)
from src.infrastructure.agents.agent_experiment_component_resolver import (
    StoredAgentExperimentComponentResolver,
)

NOW = datetime(2026, 10, 27, tzinfo=UTC)


class InMemoryVectorStoreInstances:
    def __init__(self) -> None:
        self.instance = VectorStoreInstance(
            id="vector-store-v4",
            version=4,
            name="Septiembre",
            description="",
            created_at=NOW,
            created_by="qa",
        )

    def get(self, instance_id):
        return self.instance if instance_id == self.instance.id else None

    def list(self):
        return [self.instance]


class InMemoryGenerations:
    def __init__(self) -> None:
        self.items = {
            ("vector-store-v4", 2): VectorStoreGeneration(
                instance_id="vector-store-v4",
                generation=2,
                status=VectorStoreGenerationStatus.READY,
                built_by="qa",
                created_at=NOW,
                fingerprint="f" * 64,
                manifest=(VectorStoreManifestItem("taxonomy", "tax-1", 1),),
            )
        }

    def get(self, instance_id, generation):
        return self.items.get((instance_id, generation))

    def list(self, instance_id=None):
        return list(self.items.values())


def _resolver(instances, generations):
    return StoredAgentExperimentComponentResolver(
        models=None,
        model_storage=None,
        configurations=None,
        library=None,
        vector_stores=instances,
        vector_store_generations=generations,
    )


def test_vector_store_pin_hashes_the_generation_not_the_editable_instance():
    instances, generations = InMemoryVectorStoreInstances(), InMemoryGenerations()
    resolver = _resolver(instances, generations)
    pin = resolver.pin("vector_store", "vector-store-v4", "2")
    assert pin is not None and pin.version == "2"

    # Renaming the instance or editing its manifest later builds a new
    # generation; the pinned one keeps resolving to the same content.
    instances.instance = replace(instances.instance, name="Renombrada", updated_at=NOW)
    resolved = resolver.resolve(pin)
    assert resolved is not None
    assert resolved.reference.content_sha256 == pin.content_sha256
    assert resolved.content["generation"] == 2

    generations.items[("vector-store-v4", 2)] = replace(
        generations.items[("vector-store-v4", 2)],
        status=VectorStoreGenerationStatus.RETIRED,
    )
    assert resolver.resolve(pin) is None


def _configuration(enabled: bool, generation: int | None):
    segments = default_segments()
    segments["tarjetas"].enabled = enabled
    research = segments["tarjetas"].agent.classification.delegated_research.vector_store
    research.enabled = True
    research.vector_store_instance_id = "vector-store-v4"
    research.vector_store_generation = generation
    return type("Config", (), {"segments": segments})()


def test_baseline_vector_store_is_the_one_the_active_configuration_searches():
    resolver = _resolver(InMemoryVectorStoreInstances(), InMemoryGenerations())
    assert resolver._active_vector_store(_configuration(True, 2)) == (
        "vector-store-v4",
        2,
    )
    # Without a pinned tool in an enabled segment the pipeline uses no vector
    # store: the newest READY generation is pinned so sessions can start; its
    # pin only reaches steps whose tool is enabled.
    assert resolver._active_vector_store(_configuration(False, 2)) == (
        "vector-store-v4",
        2,
    )
    assert resolver._active_vector_store(_configuration(True, None)) == (
        "vector-store-v4",
        2,
    )
    empty = InMemoryGenerations()
    empty.items.clear()
    assert _resolver(InMemoryVectorStoreInstances(), empty)._active_vector_store(
        _configuration(False, None)
    ) is None


class InMemoryConfigurations:
    def __init__(self, record) -> None:
        self.record = record

    def get(self, configuration_id, version):
        return self.record


def test_configuration_pin_hash_is_unchanged_for_versions_without_generations():
    from src.domain.configurations.entities import (
        ConfigurationRecord,
        GeneralSettings,
        InfraSettings,
        TestSettings,
    )

    record = ConfigurationRecord(
        configuration_id="cfg",
        version=1,
        name="Producción",
        description="",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=TestSettings(),
        created_at=NOW,
        updated_at=NOW,
    )
    resolver = StoredAgentExperimentComponentResolver(
        models=None,
        model_storage=None,
        configurations=InMemoryConfigurations(record),
        library=None,
        vector_stores=None,
        vector_store_generations=None,
    )
    content = resolver._configuration(
        ComponentVersionReference("configuration", "cfg", "1", "0" * 64)
    )

    def without_field(value):
        if isinstance(value, dict):
            return {
                key: without_field(item)
                for key, item in value.items()
                if key != "vector_store_generation"
            }
        if isinstance(value, list):
            return [without_field(item) for item in value]
        return value

    # Same content as before the field existed, so pins taken then still match.
    legacy = without_field(asdict(record))
    assert json.dumps(content, sort_keys=True, default=str) == json.dumps(
        legacy, sort_keys=True, default=str
    )
