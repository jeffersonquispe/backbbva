from __future__ import annotations

import math
import time
from dataclasses import asdict, fields, is_dataclass
from enum import Enum
from typing import Any

from src.application.dtos.configuration_dtos import CreateConfigurationInput
from src.application.dtos.model_dtos import CreateModelInput
from src.application.errors import DomainException
from src.application.ports.agent_specialist_executor_port import (
    AgentSpecialistExecution,
    AgentSpecialistExecutor,
)
from src.application.ports.agent_subagent_port import AgentSubagentInput
from src.application.ports.configuration_port import ConfigurationRepository
from src.application.ports.fraud_knowledge_port import (
    DocumentType,
    SearchPipeline,
)
from src.application.ports.model_port import (
    ModelRepository,
    ModelStatus,
    TrainingConfig,
)
from src.application.ports.modus_operandi_library_port import (
    ModusOperandiLibraryRepository,
)
from src.application.ports.personal_data_masker_port import PersonalDataMasker
from src.application.ports.similar_case_library_port import (
    SimilarCaseLibraryRepository,
)
from src.application.ports.taxonomy_library_port import TaxonomyLibraryRepository
from src.application.ports.vector_store_instance_port import (
    VectorStoreInstanceRepository,
)
from src.application.ports.watchlist_port import WatchlistRepository
from src.application.use_cases.configurations.create_configuration import (
    CreateConfigurationUseCase,
)
from src.application.use_cases.configurations.test_configuration import (
    PreviewConfigurationUseCase,
)
from src.application.use_cases.fraud_knowledge.search_fraud_knowledge import (
    SearchFraudKnowledgeUseCase,
)
from src.application.use_cases.models.create_model import CreateModelUseCase
from src.application.use_cases.models.start_model_training import (
    StartModelTrainingUseCase,
)
from src.application.use_cases.vector_store_instances.build_vector_store_generation import (
    BuildVectorStoreGenerationUseCase,
)
from src.application.use_cases.vector_store_instances.create_vector_store_instance import (
    CreateVectorStoreInstanceUseCase,
)
from src.domain.configurations.entities import (
    ResolutionTag,
)
from src.domain.fraud_knowledge.library_entities import (
    FALLBACK_RESOLUTION_TAGS,
    PRIMARY_RESOLUTION_TAGS,
)


class ConfigurationSpecialistExecutor(AgentSpecialistExecutor):
    def __init__(
        self,
        *,
        configurations: ConfigurationRepository,
        preview: PreviewConfigurationUseCase,
        create: CreateConfigurationUseCase,
    ) -> None:
        self._configurations = configurations
        self._preview = preview
        self._create = create

    def context(self, request: AgentSubagentInput) -> dict[str, Any]:
        active = self._configurations.get_active()
        editable = None
        if active is not None:
            snapshot = asdict(active)
            editable = {
                key: snapshot[key]
                for key in ("general", "test", "segments")
                if key in snapshot
            }
        return {
            "active_configuration_id": active.configuration_id if active else None,
            "active_configuration_version": active.version if active else None,
            "editable_configuration": editable,
            "editable_roots": ["general", "test", "segments"],
        }

    def execute(
        self,
        request: AgentSubagentInput,
        experiment: dict[str, Any],
    ) -> AgentSpecialistExecution:
        changes = experiment.get("changes")
        if not isinstance(changes, list) or not changes:
            return _rejected("CONFIGURATION_CHANGES_REQUIRED")
        active = self._configurations.get_active()
        draft = _configuration_input(active)
        if draft is None:
            return _rejected("ACTIVE_CONFIGURATION_REQUIRED")
        for change in changes:
            if not isinstance(change, dict) or not _apply_configuration_change(
                draft, change
            ):
                return _rejected("CONFIGURATION_PATH_OR_VALUE_INVALID")
        try:
            preview = self._preview.execute(draft)
            idempotency_actor = f"agent:{request.session_id}:{request.iteration_number}"
            existing = next(
                (
                    item
                    for item in self._configurations.list_versions(
                        active.configuration_id
                    )
                    if item.created_by == idempotency_actor
                ),
                None,
            )
            candidate = existing or self._create.execute(
                CreateConfigurationInput(
                    name=draft.name,
                    configuration_id=draft.configuration_id,
                    based_on_version=draft.based_on_version,
                    description=draft.description,
                    general=draft.general,
                    infra=draft.infra,
                    test=draft.test,
                    segments=draft.segments,
                    created_by=idempotency_actor,
                )
            )
        except (RuntimeError, ValueError, TypeError):
            return _rejected("CONFIGURATION_CANDIDATE_REJECTED")
        return AgentSpecialistExecution(
            status="PASSED",
            contribution={
                "candidate_configuration_id": candidate.configuration_id,
                "candidate_configuration_version": candidate.version,
                "active": False,
            },
            safe_metrics={
                "verified_changes": len(preview.changes),
                "warnings": len(preview.warnings),
            },
        )


class LibrarySpecialistExecutor(AgentSpecialistExecutor):
    def __init__(
        self,
        *,
        taxonomies: TaxonomyLibraryRepository,
        modus_operandi: ModusOperandiLibraryRepository,
        similar_cases: SimilarCaseLibraryRepository,
        watchlists: WatchlistRepository,
        masker: PersonalDataMasker,
    ) -> None:
        self._taxonomies = taxonomies
        self._modus_operandi = modus_operandi
        self._similar_cases = similar_cases
        self._watchlists = watchlists
        self._masker = masker

    def context(self, request: AgentSubagentInput) -> dict[str, Any]:
        return {
            "active_taxonomy_ids": [
                item.id for item in self._taxonomies.list(active_only=True)
            ],
            "active_modus_operandi_count": len(
                self._modus_operandi.list(active_only=True)
            ),
            "active_similar_case_count": len(
                self._similar_cases.list(active_only=True)
            ),
            "active_watchlist_count": len(
                self._watchlists.list(active_only=True)
            ),
        }

    def execute(
        self,
        request: AgentSubagentInput,
        experiment: dict[str, Any],
    ) -> AgentSpecialistExecution:
        entity_type = experiment.get("entity_type")
        draft = experiment.get("draft")
        if not isinstance(draft, dict) or not self._has_required_fields(
            entity_type, draft
        ):
            return _rejected("LIBRARY_DRAFT_INVALID")
        if _contains_personal_data(draft, self._masker):
            return _rejected("PERSONAL_DATA_BLOCKED")
        if not self._references_exist(entity_type, draft):
            return _rejected("LIBRARY_REFERENCE_INVALID")
        if self._is_duplicate(entity_type, draft):
            return _rejected("LIBRARY_DUPLICATE")
        if entity_type == "modus_operandi" and not _valid_playbook(
            draft.get("playbook")
        ):
            return _rejected("PLAYBOOK_FALLBACK_INVALID")
        return AgentSpecialistExecution(
            status="PASSED",
            contribution={"draft_only": True, "entity_type": entity_type},
            safe_metrics={"checks_passed": 4, "live_entity_writes": 0},
        )

    @staticmethod
    def _has_required_fields(entity_type: Any, draft: dict[str, Any]) -> bool:
        required = {
            "modus_operandi": ("title", "narrative", "taxonomy_id", "playbook"),
            "taxonomy": ("code", "name", "description"),
            "similar_case": ("text", "modus_operandi_id", "taxonomy_id"),
            "watchlist": ("name", "description", "list_type", "values"),
        }.get(entity_type)
        if not required:
            return False
        for key in required:
            if key not in draft or draft[key] in (None, ""):
                return False
            if isinstance(draft[key], list) and not draft[key]:
                return False
        return True

    def _references_exist(self, entity_type: Any, draft: dict[str, Any]) -> bool:
        if entity_type == "modus_operandi":
            return self._taxonomies.get(str(draft["taxonomy_id"])) is not None
        if entity_type == "similar_case":
            return (
                self._modus_operandi.get(str(draft["modus_operandi_id"])) is not None
                and self._taxonomies.get(str(draft["taxonomy_id"])) is not None
            )
        return True

    def _is_duplicate(self, entity_type: Any, draft: dict[str, Any]) -> bool:
        if entity_type == "modus_operandi":
            value = str(draft["title"]).strip().casefold()
            return any(
                item.title.strip().casefold() == value
                for item in self._modus_operandi.list(active_only=True)
            )
        if entity_type == "taxonomy":
            value = str(draft["code"]).strip().casefold()
            return any(
                item.code.strip().casefold() == value
                for item in self._taxonomies.list(active_only=True)
            )
        if entity_type == "similar_case":
            value = str(draft["text"]).strip().casefold()
            return any(
                item.text.strip().casefold() == value
                for item in self._similar_cases.list(active_only=True)
            )
        if entity_type == "watchlist":
            value = str(draft["name"]).strip().casefold()
            return any(
                item.name.strip().casefold() == value
                for item in self._watchlists.list(active_only=True)
            )
        return True


class VectorStoreSpecialistExecutor(AgentSpecialistExecutor):
    def __init__(
        self,
        *,
        instances: VectorStoreInstanceRepository,
        create: CreateVectorStoreInstanceUseCase,
        build: BuildVectorStoreGenerationUseCase,
        search: SearchFraudKnowledgeUseCase,
    ) -> None:
        self._instances = instances
        self._create = create
        self._build = build
        self._search = search

    def context(self, request: AgentSubagentInput) -> dict[str, Any]:
        return {
            "manifests": [
                {
                    "version": item.version,
                    "instance_id": item.id,
                    "asset_count": len(self._instances.list_assets(item.id)),
                }
                for item in self._instances.list()
            ],
            "authorized_queries": [request.hypothesis],
        }

    def execute(
        self,
        request: AgentSubagentInput,
        experiment: dict[str, Any],
    ) -> AgentSpecialistExecution:
        manifest_version = experiment.get("manifest_version")
        queries = experiment.get("authorized_queries")
        if not isinstance(queries, list) or request.hypothesis not in queries:
            return _rejected("VECTOR_QUERY_NOT_AUTHORIZED")
        source = next(
            (
                item
                for item in self._instances.list()
                if item.version == manifest_version
            ),
            None,
        )
        if source is None:
            return _rejected("VECTOR_MANIFEST_UNAVAILABLE")
        assets = self._instances.list_assets(source.id)
        if not assets:
            return _rejected("VECTOR_MANIFEST_EMPTY")
        candidate_name = f"agent-{request.session_id}-{request.iteration_number}"
        candidate = next(
            (item for item in self._instances.list() if item.name == candidate_name),
            None,
        )
        try:
            if candidate is None:
                candidate = self._create.execute(
                    name=candidate_name,
                    description="Generación candidata del optimizador",
                    created_by="agent",
                    assets=assets,
                )
            # Builds a candidate generation only; nothing is published.
            generation = self._build.execute(candidate.id, actor="agent").generation
            hits = len(
                self._search.execute(
                    request.hypothesis,
                    pipeline=SearchPipeline.BALANCED,
                    vector_store_id=candidate.id,
                    vector_store_generation=generation.generation,
                    document_type=DocumentType.MODUS_OPERANDI,
                    top_k=5,
                )
            )
        except (RuntimeError, ValueError, TypeError, DomainException):
            return _rejected("VECTOR_CANDIDATE_BUILD_FAILED")
        if hits == 0:
            return _rejected("VECTOR_CANDIDATE_VERIFICATION_FAILED")
        return AgentSpecialistExecution(
            status="PASSED",
            contribution={
                "candidate_instance_id": candidate.id,
                "candidate_instance_version": candidate.version,
                "candidate_generation": generation.generation,
                "source_manifest_version": source.version,
            },
            safe_metrics={
                "source_assets": len(assets),
                "authorized_queries": 1,
                "queries_with_results": 1,
                "aggregate_hits": hits,
            },
        )


class XGBoostSpecialistExecutor(AgentSpecialistExecutor):
    def __init__(
        self,
        *,
        models: ModelRepository,
        create: CreateModelUseCase,
        start_training: StartModelTrainingUseCase,
    ) -> None:
        self._models = models
        self._create = create
        self._start_training = start_training

    def context(self, request: AgentSubagentInput) -> dict[str, Any]:
        active = self._models.get_active()
        if active is None:
            return {"authorized_baseline_available": False}
        return {
            "authorized_baseline_available": True,
            "dataset_ref": active.dataset_name,
            "target_field": active.target_field,
            "positive_labels": active.positive_labels,
            "feature_transforms": [
                {"field": item.field, "kind": item.kind.value}
                for item in active.feature_transforms
            ],
            "baseline_metrics": active.metrics,
            "approved_parameter_ranges": {
                "n_estimators": [1, 2000],
                "max_depth": [1, 16],
                "learning_rate": [0.001, 0.5],
                "subsample": [0.1, 1.0],
                "colsample_bytree": [0.1, 1.0],
            },
        }

    def execute(
        self,
        request: AgentSubagentInput,
        experiment: dict[str, Any],
    ) -> AgentSpecialistExecution:
        baseline = self._models.get_active()
        parameters = experiment.get("parameters")
        if baseline is None or not isinstance(parameters, dict):
            return _rejected("AUTHORIZED_MODEL_BASELINE_REQUIRED")
        # Dataset selection is server-owned: proposals may tune parameters,
        # while training always inherits the authorized active baseline's
        # dataset and feature contract below.
        training = TrainingConfig(**vars(baseline.training_config))
        for key, value in parameters.items():
            if not hasattr(training, key):
                return _rejected("TRAINING_PARAMETER_NOT_SUPPORTED")
            setattr(training, key, value)
        tag = f"agent-{request.session_id}-{request.iteration_number}"
        candidate = next((item for item in self._models.list() if item.tag == tag), None)
        try:
            if candidate is None:
                created = self._create.execute(
                    CreateModelInput(
                        tag=tag,
                        description="Candidato de optimización ARIA",
                        dataset_name=baseline.dataset_name,
                        target_field=baseline.target_field,
                        positive_labels=list(baseline.positive_labels),
                        feature_transforms=baseline.feature_transforms,
                        created_by="agent",
                        historical_features=baseline.historical_features,
                        feature_configuration=baseline.feature_configuration,
                        training_config=training,
                    )
                )
                candidate = self._models.get(created.id)
            if candidate is None:
                return _rejected("MODEL_CANDIDATE_LOST")
            if candidate.status == ModelStatus.DRAFT:
                self._start_training.execute(candidate.id)
            elif candidate.status == ModelStatus.READY:
                return _verify_trained_model(candidate, baseline)
            elif candidate.status == ModelStatus.FAILED:
                return _rejected("MODEL_TRAINING_FAILED")
        except (RuntimeError, ValueError, TypeError):
            return _rejected("MODEL_CANDIDATE_START_FAILED")
        try:
            requested_wait = int(request.budget.get("seconds", 1) or 1)
        except (TypeError, ValueError):
            return _rejected("MODEL_TRAINING_BUDGET_INVALID")
        max_wait = min(max(requested_wait, 1), 180)
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            trained = self._models.get(candidate.id)
            if trained is None:
                return _rejected("MODEL_CANDIDATE_LOST")
            if trained.status == ModelStatus.READY:
                return _verify_trained_model(trained, baseline)
            if trained.status == ModelStatus.FAILED:
                return _rejected("MODEL_TRAINING_FAILED")
            time.sleep(0.5)
        return AgentSpecialistExecution(
            status="PENDING_VERIFICATION",
            contribution={"candidate_model_id": str(candidate.id)},
            safe_metrics={"training_dispatched": 1},
        )


def _configuration_input(active) -> CreateConfigurationInput | None:
    if active is None:
        return None
    return CreateConfigurationInput(
        name=active.name,
        configuration_id=active.configuration_id,
        based_on_version=active.version,
        description=active.description,
        general=active.general,
        infra=active.infra,
        test=active.test,
        created_by="agent",
        segments=active.segments,
    )


def _apply_configuration_change(
    draft: CreateConfigurationInput, change: dict[str, Any]
) -> bool:
    path = change.get("path")
    if not isinstance(path, str) or "value" not in change:
        return False
    parts = path.split(".")
    if not parts or parts[0] not in {"general", "test", "segments"}:
        return False
    current: Any = draft
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                return False
            current = current[part]
        elif is_dataclass(current):
            if part not in {item.name for item in fields(current)}:
                return False
            current = getattr(current, part)
        else:
            return False
    leaf = parts[-1]
    value = change["value"]
    if isinstance(current, dict):
        if leaf not in current:
            return False
        expected = current[leaf]
    elif is_dataclass(current) and leaf in {item.name for item in fields(current)}:
        expected = getattr(current, leaf)
    else:
        return False
    if isinstance(expected, Enum):
        try:
            value = type(expected)(value)
        except (ValueError, TypeError):
            return False
    elif isinstance(expected, bool):
        if not isinstance(value, bool):
            return False
    elif isinstance(expected, int):
        if not isinstance(value, int) or isinstance(value, bool):
            return False
    elif isinstance(expected, float):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if not math.isfinite(float(value)):
            return False
        value = float(value)
    elif isinstance(expected, str):
        if not isinstance(value, str):
            return False
    else:
        return False
    if isinstance(current, dict):
        current[leaf] = value
    else:
        setattr(current, leaf, value)
    return True


def _contains_personal_data(value: Any, masker: PersonalDataMasker) -> bool:
    if isinstance(value, str):
        return bool(masker.mask(value).counts)
    if isinstance(value, list):
        return any(_contains_personal_data(item, masker) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_personal_data(key, masker)
            or _contains_personal_data(item, masker)
            for key, item in value.items()
        )
    return False


def _valid_playbook(playbook: Any) -> bool:
    if not isinstance(playbook, dict):
        return False
    for key, allowed in (
        ("resolution", PRIMARY_RESOLUTION_TAGS),
        ("if_no_voicebot", FALLBACK_RESOLUTION_TAGS),
        ("if_no_analyst", FALLBACK_RESOLUTION_TAGS),
    ):
        behavior = playbook.get(key)
        if not isinstance(behavior, dict):
            return False
        tag = behavior.get("resolution_tag")
        try:
            if ResolutionTag(tag) not in allowed:
                return False
        except ValueError:
            return False
    return True


def _verify_trained_model(candidate, baseline) -> AgentSpecialistExecution:
    report = candidate.training_report or {}
    partitions = report.get("partitions")
    required_partitions = {"training", "validation", "calibration"}
    if (
        not candidate.storage_ref
        or not isinstance(report.get("dataset_sha256"), str)
        or not report.get("dataset_sha256")
        or not isinstance(partitions, dict)
        or not required_partitions.issubset(partitions)
        or not isinstance(report.get("thresholds"), list)
        or not report["thresholds"]
        or report.get("threshold_selection") != "validation_f1"
        or report.get("evaluation_partition") == "final"
        or candidate.active
    ):
        return _rejected("MODEL_REPORT_INCOMPLETE")
    metrics = candidate.metrics or {}
    baseline_metrics = baseline.metrics or {}
    return AgentSpecialistExecution(
        status="PASSED",
        contribution={
            "candidate_model_id": str(candidate.id),
            "candidate_model_tag": candidate.tag,
            "candidate_active": False,
            "baseline_model_id": str(baseline.id),
        },
        safe_metrics={
            "precision": metrics.get("precision", 0.0),
            "recall": metrics.get("recall", 0.0),
            "baseline_precision": baseline_metrics.get("precision", 0.0),
            "baseline_recall": baseline_metrics.get("recall", 0.0),
            "partition_count": len(partitions),
            "threshold_count": len(report["thresholds"]),
        },
    )


def _rejected(code: str) -> AgentSpecialistExecution:
    return AgentSpecialistExecution(
        status="FAILED",
        safe_metrics={"checks_passed": 0},
        error_code=code,
    )
