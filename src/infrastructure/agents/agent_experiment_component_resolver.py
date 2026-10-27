from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
from uuid import UUID

from src.application.ports.agent_experiment_component_port import (
    ResolvedAgentComponent,
)
from src.application.ports.configuration_port import ConfigurationRepository
from src.application.ports.model_port import ModelRepository
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.ports.vector_store_generation_port import (
    VectorStoreGenerationRepository,
    VectorStoreGenerationStatus,
)
from src.application.ports.vector_store_instance_port import (
    VectorStoreInstanceRepository,
)
from src.domain.agents.experiment import ComponentVersionReference
from src.domain.fraud_knowledge.vector_store_generations import (
    iter_vector_store_research,
)


class StoredAgentExperimentComponentResolver:
    """Load versioned component records and verify their content pin upstream.

    Model pins include the digest of the stored model bundle. Configuration
    pins use their numbered versions and vector-store pins the immutable
    generation number (a RETIRED generation no longer resolves). Library
    pins use the immutable revision SHA-256 and fail closed for entries
    without a snapshot.
    """

    def __init__(
        self,
        *,
        models: ModelRepository,
        model_storage: ObjectStoragePort,
        configurations: ConfigurationRepository,
        library: ModusOperandiLibraryRepository,
        vector_stores: VectorStoreInstanceRepository,
        vector_store_generations: VectorStoreGenerationRepository,
    ) -> None:
        self._models = models
        self._model_storage = model_storage
        self._configurations = configurations
        self._library = library
        self._vector_stores = vector_stores
        self._vector_store_generations = vector_store_generations

    def resolve(
        self, reference: ComponentVersionReference
    ) -> ResolvedAgentComponent | None:
        try:
            if reference.component == "model":
                content = self._model(reference)
            elif reference.component == "configuration":
                content = self._configuration(reference)
            elif reference.component == "library":
                content = self._library_revision(reference)
            elif reference.component == "vector_store":
                content = self._vector_store(reference)
            else:
                return None
        except (KeyError, TypeError, ValueError, OSError):
            return None
        if content is None:
            return None
        actual = ComponentVersionReference.pin(
            reference.component,
            reference.entity_id,
            reference.version,
            content,
        )
        if actual.content_sha256 != reference.content_sha256:
            return None
        return ResolvedAgentComponent(reference=actual, content=content)

    def pin(
        self, component: str, entity_id: str, version: str
    ) -> ComponentVersionReference | None:
        reference = ComponentVersionReference(component, entity_id, version, "0" * 64)
        try:
            content = {
                "model": lambda: self._model(reference),
                "configuration": lambda: self._configuration(reference),
                "library": lambda: self._library_revision(reference),
                "vector_store": lambda: self._vector_store(reference),
            }.get(component, lambda: None)()
        except (KeyError, TypeError, ValueError, OSError):
            return None
        if content is None:
            return None
        pinned_version = (
            content["artifact_sha256"]
            if component == "model" and isinstance(content, dict)
            else version
        )
        return ComponentVersionReference.pin(
            component, entity_id, pinned_version, content
        )

    def active_baseline(self) -> tuple[ComponentVersionReference, ...]:
        model = self._models.get_active()
        configuration = self._configurations.get_active()
        libraries = self._library.list(active_only=True)
        vector_store = (
            self._active_vector_store(configuration) if configuration else None
        )
        if model is None or configuration is None or not libraries or not vector_store:
            raise ValueError("ACTIVE_PIPELINE_COMPONENT_MISSING")
        library_entry = sorted(libraries, key=lambda item: item.id)[0]
        revision = self._library.ensure_current_revision(library_entry.id)
        if revision is None:
            raise ValueError("ACTIVE_LIBRARY_REVISION_UNAVAILABLE")
        library_version = revision.revision_sha256
        pins = (
            self.pin("model", str(model.id), model.tag),
            self.pin(
                "configuration",
                configuration.configuration_id,
                str(configuration.version),
            ),
            self.pin("library", library_entry.id, library_version),
            self.pin("vector_store", vector_store[0], str(vector_store[1])),
        )
        if any(pin is None for pin in pins):
            raise ValueError("ACTIVE_PIPELINE_COMPONENT_PIN_FAILED")
        return tuple(pin for pin in pins if pin is not None)

    def _model(self, reference: ComponentVersionReference) -> dict:
        model = self._models.get(UUID(reference.entity_id))
        if model is None:
            raise ValueError("MODEL_PIN_UNRESOLVED")
        if len(reference.version) == 64 and all(
            char in "0123456789abcdef" for char in reference.version
        ):
            storage_key = f"models/sha256/{reference.version}.joblib"
            artifact = self._model_storage.get_bytes(storage_key)
        else:
            if model.storage_ref is None or model.tag != reference.version:
                raise ValueError("MODEL_PIN_UNRESOLVED")
            artifact = self._model_storage.get_bytes(model.storage_ref)
            digest = sha256(artifact).hexdigest()
            storage_key = f"models/sha256/{digest}.joblib"
            try:
                self._model_storage.get_bytes(storage_key)
            except (KeyError, OSError):
                self._model_storage.put_bytes(
                    key=storage_key,
                    content=artifact,
                    content_type="application/octet-stream",
                )
        digest = sha256(artifact).hexdigest()
        if len(reference.version) == 64 and digest != reference.version:
            raise ValueError("MODEL_PIN_HASH_MISMATCH")
        return {
            "model_id": str(model.id),
            "artifact_sha256": digest,
            "artifact_bytes": artifact,
        }

    def _configuration(self, reference: ComponentVersionReference) -> dict | None:
        version = int(reference.version)
        config = self._configurations.get(reference.entity_id, version)
        if config is None:
            return None
        return _without_unset_generation_pins(asdict(config))

    def _library_revision(self, reference: ComponentVersionReference) -> dict | None:
        revision = self._library.get_revision(reference.entity_id, reference.version)
        if revision is None or revision.revision_sha256 != reference.version:
            return None
        return asdict(revision.content)

    def _active_vector_store(self, configuration) -> tuple[str, int] | None:
        """The (instance, generation) the active configuration searches: the
        first pinned vector-store tool in enabled segment/step order.

        When the active pipeline uses no vector store, the newest READY
        generation of the newest instance is pinned instead, so the optimizer
        can still open sessions and explore the vector-store lever. That pin
        does not change replay results: evaluation applies a vector-store pin
        only to steps whose tool is enabled."""
        enabled = {key: value for key, value in configuration.segments.items() if value.enabled}
        for _, _, research in iter_vector_store_research(enabled):
            if research.vector_store_generation is not None:
                return research.vector_store_instance_id or "", (
                    research.vector_store_generation
                )
        ready = [
            item
            for item in self._vector_store_generations.list()
            if item.status == VectorStoreGenerationStatus.READY
        ]
        if not ready:
            return None
        versions = {item.id: item.version for item in self._vector_stores.list()}
        newest = max(
            ready,
            key=lambda item: (versions.get(item.instance_id, 0), item.generation),
        )
        return newest.instance_id, newest.generation

    def _vector_store(self, reference: ComponentVersionReference) -> dict | None:
        instance = self._vector_stores.get(reference.entity_id)
        generation = self._vector_store_generations.get(
            reference.entity_id, int(reference.version)
        )
        if (
            instance is None
            or generation is None
            or generation.status != VectorStoreGenerationStatus.READY
        ):
            return None
        # Only immutable facts: renaming the instance or editing its
        # manifest later must not change what this pin hashes to.
        return {
            "instance": {"id": instance.id, "version": instance.version},
            "generation": generation.generation,
            "fingerprint": generation.fingerprint,
            "assets": [asdict(item) for item in generation.manifest],
        }


def _without_unset_generation_pins(value):
    """Drops ``vector_store_generation: None`` so versions saved before
    generations existed keep the content hash they were pinned with."""
    if isinstance(value, dict):
        return {
            key: _without_unset_generation_pins(item)
            for key, item in value.items()
            if not (key == "vector_store_generation" and item is None)
        }
    if isinstance(value, list):
        return [_without_unset_generation_pins(item) for item in value]
    return value
