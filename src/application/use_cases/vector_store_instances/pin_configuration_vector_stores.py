from __future__ import annotations

import copy

from src.application.ports.vector_store_generation_port import (
    VectorStoreGenerationRepository,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    VectorStoreGenerationUnavailableError,
    resolve_vector_store_generation,
)
from src.application.use_cases.vector_store_instances.build_vector_store_generation import (
    BuildVectorStoreGenerationUseCase,
)
from src.domain.configurations.entities import ConfigurationRecord, SegmentSettings
from src.domain.fraud_knowledge.vector_store_generations import (
    configuration_vector_store_pins,
    iter_vector_store_research,
)


class PinConfigurationVectorStoresUseCase:
    """Fixes the exact generation every vector-store tool of a configuration
    version searches, before the version is saved.

    A tool with an instance but no generation gets the generation of that
    instance's current manifest - built now when no READY generation holds
    it yet. An explicit generation must be READY. Since activating a version
    requires a passed test of that same version, the documents a test ran
    against are exactly the ones its deploy request publishes."""

    def __init__(
        self,
        build: BuildVectorStoreGenerationUseCase,
        generations: VectorStoreGenerationRepository,
    ) -> None:
        self._build = build
        self._generations = generations

    def execute(
        self, segments: dict[str, SegmentSettings], *, actor: str
    ) -> dict[str, SegmentSettings]:
        pinned = copy.deepcopy(segments)
        built: dict[str, int] = {}
        for _, _, research in iter_vector_store_research(pinned):
            instance_id = research.vector_store_instance_id or ""
            if research.vector_store_generation is not None:
                resolve_vector_store_generation(
                    self._generations, instance_id, research.vector_store_generation
                )
                continue
            if instance_id not in built:
                built[instance_id] = self._build.execute(
                    instance_id, actor=actor
                ).generation.generation
            research.vector_store_generation = built[instance_id]
        return pinned

    def verify(self, configuration: ConfigurationRecord) -> None:
        """Raises VectorStoreGenerationUnavailableError when a pinned
        generation can no longer be searched (failed, retired) or a tool was
        saved before generations existed and was never pinned."""
        for pin in configuration_vector_store_pins(configuration):
            if pin.generation is None:
                raise VectorStoreGenerationUnavailableError(
                    f"vector store {pin.instance_id} has no pinned generation in "
                    f"configuration {configuration.configuration_id} "
                    f"v{configuration.version}; save the configuration again"
                )
            resolve_vector_store_generation(
                self._generations, pin.instance_id, pin.generation
            )
