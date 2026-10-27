from __future__ import annotations

from dataclasses import dataclass, field

from src.application.ports.configuration_port import ConfigurationRepository
from src.application.ports.vector_store_generation_port import (
    VectorStoreGeneration,
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
)
from src.application.ports.vector_store_instance_port import (
    VectorStoreInstance,
    VectorStoreInstanceRepository,
)
from src.domain.fraud_knowledge.vector_store_generations import (
    configuration_vector_store_pins,
)


@dataclass(frozen=True)
class VectorStoreInstanceSummary:
    instance: VectorStoreInstance
    latest_ready_generation: int | None
    # Generations the active configuration searches right now.
    production_generations: tuple[int, ...] = ()


@dataclass(frozen=True)
class VectorStoreGenerationView:
    generation: VectorStoreGeneration
    in_production: bool
    # "<configuration_id>@v<version>" of every saved version pinning it.
    pinned_by: tuple[str, ...] = field(default_factory=tuple)


class ListVectorStoreInstancesUseCase:
    def __init__(
        self,
        repository: VectorStoreInstanceRepository,
        generations: VectorStoreGenerationRepository,
        configurations: ConfigurationRepository,
    ) -> None:
        self._repository = repository
        self._generations = generations
        self._configurations = configurations

    def summarize(self, instance: VectorStoreInstance) -> VectorStoreInstanceSummary:
        return self._summaries([instance], self._generations.list(instance.id))[0]

    def execute(self) -> list[VectorStoreInstanceSummary]:
        return self._summaries(self._repository.list(), self._generations.list())

    def _summaries(
        self,
        instances: list[VectorStoreInstance],
        generations: list[VectorStoreGeneration],
    ) -> list[VectorStoreInstanceSummary]:
        ready: dict[str, int] = {}
        for item in generations:
            if item.status == VectorStoreGenerationStatus.READY:
                ready[item.instance_id] = max(
                    item.generation, ready.get(item.instance_id, 0)
                )
        active = self._configurations.get_active()
        live = configuration_vector_store_pins(active) if active else set()
        return [
            VectorStoreInstanceSummary(
                instance=instance,
                latest_ready_generation=ready.get(instance.id),
                production_generations=tuple(
                    sorted(
                        pin.generation
                        for pin in live
                        if pin.instance_id == instance.id and pin.generation is not None
                    )
                ),
            )
            for instance in instances
        ]

    def generations(self, instance_id: str) -> list[VectorStoreGenerationView]:
        pinned: dict[int, list[str]] = {}
        active = self._configurations.get_active()
        live = {
            pin.generation
            for pin in (configuration_vector_store_pins(active) if active else set())
            if pin.instance_id == instance_id and pin.generation is not None
        }
        for (configuration_id, version), pins in (
            self._configurations.list_vector_store_pins().items()
        ):
            for pin in pins:
                if pin.instance_id == instance_id and pin.generation is not None:
                    pinned.setdefault(pin.generation, []).append(
                        f"{configuration_id}@v{version}"
                    )
        return [
            VectorStoreGenerationView(
                generation=item,
                in_production=item.generation in live,
                pinned_by=tuple(sorted(set(pinned.get(item.generation, [])))),
            )
            for item in reversed(self._generations.list(instance_id))
        ]
