from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.ports.agent_subagent_port import AgentSubagentInput
from src.application.ports.fraud_knowledge_port import DocumentType, SearchPipeline
from src.application.ports.model_port import (
    FieldTransform,
    FieldTransformKind,
    ModelRecord,
    ModelStatus,
    TrainingConfig,
)
from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)
from src.application.ports.vector_store_instance_port import (
    KnowledgeAssetType,
    VectorStoreInstance,
    VectorStoreInstanceAsset,
)
from src.application.use_cases.configurations.create_configuration import (
    CreateConfigurationUseCase,
)
from src.application.use_cases.configurations.test_configuration import (
    PreviewConfigurationUseCase,
)
from src.domain.configurations.entities import (
    ConfigurationRecord,
    GeneralSettings,
    InfraSettings,
)
from src.domain.configurations.entities import (
    TestSettings as ConfigurationTestSettings,
)
from src.infrastructure.agents.optimizer_specialist_executors import (
    ConfigurationSpecialistExecutor,
    LibrarySpecialistExecutor,
    VectorStoreSpecialistExecutor,
    _apply_configuration_change,
    _verify_trained_model,
)


class NoPersonalDataMasker(PersonalDataMasker):
    def mask(self, text: str) -> MaskedPersonalData:
        return MaskedPersonalData(text=text, counts={})


class EmptyLibraryRepository:
    def list(self, *, active_only: bool = False) -> list:
        return []

    def get(self, entry_id: str):
        return None


class InMemoryConfigurationRepository:
    def __init__(self, active: ConfigurationRecord):
        self.versions = [active]

    def get_active(self) -> ConfigurationRecord:
        return self.versions[0]

    def get_latest_version(self, configuration_id: str) -> ConfigurationRecord:
        return self.versions[-1]

    def list_versions(self, configuration_id: str) -> list[ConfigurationRecord]:
        return list(self.versions)

    def create(self, config: ConfigurationRecord) -> ConfigurationRecord:
        self.versions.append(config)
        return config


class InMemoryVectorInstances:
    def __init__(self, source: VectorStoreInstance, asset: VectorStoreInstanceAsset):
        self.source = source
        self.asset = asset

    def list(self) -> list[VectorStoreInstance]:
        return [self.source]

    def list_assets(self, instance_id: str) -> list[VectorStoreInstanceAsset]:
        return [self.asset] if instance_id == self.source.id else []


class CreateCandidateInstance:
    def __init__(self, candidate: VectorStoreInstance):
        self.candidate = candidate

    def execute(self, **kwargs) -> VectorStoreInstance:
        return self.candidate


class BuildCandidateInstance:
    def __init__(self, candidate: VectorStoreInstance):
        self.candidate = candidate

    def execute(self, instance_id: str, *, actor: str) -> VectorStoreInstance:
        return self.candidate


class SearchCandidate:
    def execute(
        self,
        query: str,
        *,
        pipeline: SearchPipeline,
        vector_store_id: str,
        document_type: DocumentType,
        top_k: int,
    ) -> list[str]:
        return ["aggregate-hit"]


def test_configuration_evaluator_accepts_editable_scalar_and_rejects_infra() -> None:
    now = datetime.now(UTC)
    active = ConfigurationRecord(
        configuration_id="config",
        version=1,
        name="active",
        description="baseline",
        active=True,
        general=GeneralSettings(),
        infra=InfraSettings(),
        test=ConfigurationTestSettings(),
        created_at=now,
        updated_at=now,
    )
    repository = InMemoryConfigurationRepository(active)
    executor = ConfigurationSpecialistExecutor(
        configurations=repository,
        preview=PreviewConfigurationUseCase(repository),
        create=CreateConfigurationUseCase(repository),
    )
    result = executor.execute(
        AgentSubagentInput("session", 1, {}, "configuration improvement", {}),
        {"changes": [{"path": "general.migration_window_enabled", "value": True}]},
    )
    assert result.status == "PASSED"
    assert result.contribution["active"] is False
    assert repository.versions[-1].general.migration_window_enabled is True
    draft = CreateConfigurationInput(name="candidate", general=GeneralSettings())
    assert not _apply_configuration_change(
        draft, {"path": "infra.api_port", "value": 9000}
    )


def test_library_evaluator_accepts_unique_taxonomy_draft_without_live_write() -> None:
    executor = LibrarySpecialistExecutor(
        taxonomies=EmptyLibraryRepository(),
        modus_operandi=EmptyLibraryRepository(),
        similar_cases=EmptyLibraryRepository(),
        watchlists=EmptyLibraryRepository(),
        masker=NoPersonalDataMasker(),
    )
    result = executor.execute(
        AgentSubagentInput("session", 1, {}, "taxonomy improvement", {}),
        {
            "entity_type": "taxonomy",
            "draft": {"code": "NEW", "name": "Nueva", "description": "Descripción"},
        },
    )
    assert result.status == "PASSED"
    assert result.contribution == {"draft_only": True, "entity_type": "taxonomy"}
    assert result.safe_metrics["live_entity_writes"] == 0


def test_library_optimizer_rejects_flag_writes_as_unsupported_experiment_type() -> None:
    executor = LibrarySpecialistExecutor(
        taxonomies=EmptyLibraryRepository(),
        modus_operandi=EmptyLibraryRepository(),
        similar_cases=EmptyLibraryRepository(),
        watchlists=EmptyLibraryRepository(),
        masker=NoPersonalDataMasker(),
    )
    result = executor.execute(
        AgentSubagentInput("session", 1, {}, "flag improvement", {}),
        {
            "entity_type": "flag",
            "draft": {"flag_type": "red", "name": "Proposed flag"},
        },
    )
    assert result.status == "FAILED"
    assert result.error_code == "LIBRARY_DRAFT_INVALID"


def test_library_optimizer_watchlist_proposal_is_draft_only() -> None:
    executor = LibrarySpecialistExecutor(
        taxonomies=EmptyLibraryRepository(),
        modus_operandi=EmptyLibraryRepository(),
        similar_cases=EmptyLibraryRepository(),
        watchlists=EmptyLibraryRepository(),
        masker=NoPersonalDataMasker(),
    )
    result = executor.execute(
        AgentSubagentInput("session", 1, {}, "watchlist improvement", {}),
        {
            "entity_type": "watchlist",
            "draft": {
                "name": "Candidate",
                "description": "Proposed only",
                "list_type": "blacklist",
                "values": ["123"],
            },
        },
    )
    assert result.status == "PASSED"
    assert result.contribution == {"draft_only": True, "entity_type": "watchlist"}
    assert result.safe_metrics["live_entity_writes"] == 0


def test_vector_store_evaluator_builds_isolated_candidate_and_searches_authorized_query() -> (
    None
):
    now = datetime.now(UTC)
    source = VectorStoreInstance(
        "source", 1, "source", "source", now, "test", promoted_version=1
    )
    candidate = VectorStoreInstance(
        "candidate", 2, "candidate", "candidate", now, "agent", promoted_version=1
    )
    asset = VectorStoreInstanceAsset(
        vector_store_instance_id="source",
        asset_type=KnowledgeAssetType.MODUS_OPERANDI,
        asset_id="asset",
        asset_version=1,
        embedding=[0.1, 0.2],
    )
    executor = VectorStoreSpecialistExecutor(
        instances=InMemoryVectorInstances(source, asset),
        create=CreateCandidateInstance(candidate),
        build=BuildCandidateInstance(candidate),
        search=SearchCandidate(),
    )
    request = AgentSubagentInput("session", 1, {}, "authorized hypothesis", {})
    result = executor.execute(
        request,
        {"manifest_version": 1, "authorized_queries": [request.hypothesis]},
    )
    assert result.status == "PASSED"
    assert result.contribution["candidate_instance_id"] == "candidate"
    assert result.safe_metrics["aggregate_hits"] == 1


def test_xgboost_evaluator_accepts_complete_inactive_candidate_report() -> None:
    baseline = ModelRecord(
        id=uuid4(),
        tag="baseline",
        description="baseline",
        status=ModelStatus.READY,
        dataset_name="authorized-dataset",
        target_field="label",
        metrics={"precision": 0.9, "recall": 0.7},
    )
    candidate = ModelRecord(
        id=uuid4(),
        tag="candidate",
        description="candidate",
        status=ModelStatus.READY,
        dataset_name="authorized-dataset",
        target_field="label",
        active=False,
        metrics={"precision": 0.92, "recall": 0.72},
        storage_ref="artifact://candidate",
        training_config=TrainingConfig(),
        feature_transforms=[FieldTransform("amount", FieldTransformKind.NUMERIC)],
        training_report={
            "dataset_sha256": "a" * 64,
            "partitions": {
                "training": {"rows": 10},
                "validation": {"rows": 4},
                "calibration": {"rows": 2},
            },
            "thresholds": [{"threshold": 0.5}],
            "threshold_selection": "validation_f1",
            "evaluation_partition": "validation-provisional",
        },
    )
    result = _verify_trained_model(candidate, baseline)
    assert result.status == "PASSED"
    assert result.safe_metrics["precision"] == 0.92
    assert result.contribution["candidate_active"] is False
