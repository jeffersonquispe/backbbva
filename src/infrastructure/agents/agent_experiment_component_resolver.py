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
from src.application.ports.vector_store_instance_port import (
    VectorStoreInstanceRepository,
)
from src.domain.agents.experiment import ComponentVersionReference


class StoredAgentExperimentComponentResolver:
    """Load versioned component records and verify their content pin upstream.

    Model pins include the digest of the stored model bundle. Configuration and
    vector-store pins use their numbered versions. Library pins use the
    immutable revision SHA-256 and fail closed for entries without a snapshot.
    """

    def __init__(
        self,
        *,
        models: ModelRepository,
        model_storage: ObjectStoragePort,
        configurations: ConfigurationRepository,
        library: ModusOperandiLibraryRepository,
        vector_stores: VectorStoreInstanceRepository,
    ) -> None:
        self._models = models
        self._model_storage = model_storage
        self._configurations = configurations
        self._library = library
        self._vector_stores = vector_stores

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
        vector_stores = [
            item
            for item in self._vector_stores.list()
            if item.promoted_version is not None
        ]
        if model is None or configuration is None or not libraries or not vector_stores:
            raise ValueError("ACTIVE_PIPELINE_COMPONENT_MISSING")
        library_entry = sorted(libraries, key=lambda item: item.id)[0]
        revision = self._library.ensure_current_revision(library_entry.id)
        if revision is None:
            raise ValueError("ACTIVE_LIBRARY_REVISION_UNAVAILABLE")
        library_version = revision.revision_sha256
        vector_store = max(vector_stores, key=lambda item: (item.version, item.id))
        pins = (
            self.pin("model", str(model.id), model.tag),
            self.pin(
                "configuration",
                configuration.configuration_id,
                str(configuration.version),
            ),
            self.pin("library", library_entry.id, library_version),
            self.pin("vector_store", vector_store.id, str(vector_store.version)),
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
        return asdict(config)

    def _library_revision(self, reference: ComponentVersionReference) -> dict | None:
        revision = self._library.get_revision(reference.entity_id, reference.version)
        if revision is None or revision.revision_sha256 != reference.version:
            return None
        return asdict(revision.content)

    def _vector_store(self, reference: ComponentVersionReference) -> dict | None:
        instance = self._vector_stores.get(reference.entity_id)
        if instance is None or str(instance.version) != reference.version:
            return None
        assets = self._vector_stores.list_assets(reference.entity_id)
        return {
            "instance": asdict(instance),
            "assets": [
                asdict(asset) for asset in sorted(assets, key=lambda a: a.relation_id)
            ],
        }
