from __future__ import annotations

import json
from functools import lru_cache

from src.application.dtos.research_dtos import ResearchSource
from src.application.ports.backup_catalog_port import BackupCatalogRepository
from src.application.ports.dataset_analysis_port import DatasetSampleRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.ports.fraud_history_archive_index_port import (
    ArchiveIndexPort,
)
from src.application.ports.fraud_history_archive_port import (
    FraudHistoryArchivePort,
)
from src.application.ports.fraud_history_archive_reader_port import (
    FraudHistoryArchiveReaderPort,
)
from src.application.ports.history_research_planner_port import HistoryResearchPlanner
from src.application.ports.legal_hold_port import LegalHoldRepository
from src.application.ports.model_scoring_port import ModelScoringPort
from src.application.ports.protected_object_keys_port import (
    ProtectedObjectKeysPort,
)
from src.application.use_cases.agent.chat_with_agent import ChatWithAgentUseCase
from src.application.use_cases.agent.evaluate_global_pipeline import (
    EvaluateGlobalPipeline,
)
from src.application.use_cases.agent.orchestrate_agent_iteration import (
    OrchestrateAgentIterationUseCase,
)
from src.application.use_cases.agent.record_agent_shadow_observation import (
    RecordAgentShadowObservation,
)
from src.application.use_cases.agent.recover_stale_agent_runs import (
    RecoverStaleAgentRunsUseCase,
)
from src.application.use_cases.alerts.document_analyst_decision import (
    DocumentAnalystDecisionUseCase,
)
from src.application.use_cases.alerts.escalate_alert_to_analyst import (
    EscalateAlertToAnalystUseCase,
)
from src.application.use_cases.alerts.execute_alert_action import (
    ExecuteAlertActionUseCase,
)
from src.application.use_cases.alerts.raw_payload import RawAlertPayloadLoader
from src.application.use_cases.alerts.resolve_alert_segment import (
    ResolveAlertSegmentUseCase,
)
from src.application.use_cases.alerts.run_alert_review_workflow import (
    RunAlertReviewWorkflowUseCase,
)
from src.application.use_cases.alerts.start_alert_test_workflow import (
    StartAlertTestWorkflowUseCase,
)
from src.application.use_cases.async_operations.reconcile_async_operations import (
    ReconcileAsyncOperationsUseCase,
)
from src.application.use_cases.datasets.analyze_dataset import AnalyzeDatasetUseCase
from src.application.use_cases.datasets.analyze_fraud_marking import (
    AnalyzeFraudMarkingUseCase,
)
from src.application.use_cases.datasets.create_mature_sample_snapshot import (
    CreateMatureSampleSnapshotUseCase,
)
from src.application.use_cases.datasets.delete_dataset import DeleteDatasetUseCase
from src.application.use_cases.datasets.preview_mature_sample import (
    PreviewMatureSampleUseCase,
)
from src.application.use_cases.fraud_review.archive_fraud_history import (
    ArchiveFraudHistory,
)
from src.application.use_cases.object_storage.apply_retention import (
    ApplyObjectStorageRetentionUseCase,
    RetentionRule,
)
from src.application.use_cases.research.delegated_research import (
    ResearchDelegationCoordinator,
    TimeBoundedResearchAgent,
    VectorStoreResearchAgent,
)
from src.application.use_cases.research.research_tool import BoundedResearchTool
from src.application.use_cases.test_runs.cleanup_test_runs import CleanupTestRunsUseCase
from src.application.use_cases.test_runs.delete_test_runs import DeleteTestRunsUseCase
from src.application.use_cases.test_runs.list_test_runs import ListTestRunsUseCase
from src.application.use_cases.test_runs.start_test_run import StartTestRunUseCase
from src.application.use_cases.vector_store_instances.cleanup_vector_store_generations import (
    CleanupVectorStoreGenerationsUseCase,
)
from src.domain.configurations.entities import (
    HistoryPandasResearchConfig,
    VectorStoreResearchConfig,
)
from src.infrastructure.agents.factories import (
    get_agent_audit_repository,
    get_agent_experiment_component_resolver,
    get_agent_release_repository,
    get_agent_verification_repository,
)
from src.infrastructure.alert_actions.mock.alert_channel_action_adapter import (
    MockAlertChannelActionAdapter,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.llm.catalog.element_llm import get_element_llm_factory
from src.infrastructure.model_serving.mcp_scoring_client import (
    MCPModelScoringClient,
)
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.agent_objective_repository import (
    DynamoAgentObjectiveRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.backup_catalog_repository import (
    DynamoBackupCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_sample_repository import (
    DynamoDatasetSampleRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_summary_repository import (
    DynamoDatasetSummaryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_index_repository import (
    DynamoFraudHistoryArchiveIndex,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_reader import (
    DynamoFraudHistoryArchiveReader,
    LegalHoldProtectedArchiveKeys,
)
from src.infrastructure.persistence.database.dynamodb.repositories.fraud_history_archive_repository import (
    DynamoFraudHistoryArchiveRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.legal_hold_repository import (
    DynamoLegalHoldRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.mature_sample_repository import (
    DynamoDatasetSamplerStateRepository,
    DynamoDatasetSnapshotRepository,
    DynamoMatureSamplerSchemaMappingRepository,
)
from src.infrastructure.persistence.dataset.minio.csv_dataset_repository import (
    MinioCsvDatasetRepository,
)
from src.infrastructure.persistence.object_storage.minio import (
    get_dataset_object_storage,
    get_model_object_storage,
    get_object_storage,
)
from src.infrastructure.queues.celery.inspector import CeleryAsyncExecutionInspector
from src.infrastructure.workflows.celery.executor import CeleryWorkflowExecutor
from src.infrastructure.workflows.celery.factories import (
    get_agent_session_repository,
    get_alert_object_storage,
    get_alert_repository,
    get_alert_schema_repository,
    get_analyst_decision_documenter,
    get_analyst_escalation_dispatcher,
    get_aric_alert_port,
    get_assistant_optimizer_settings_repository,
    get_async_operation_repository,
    get_configuration_deploy_request_repository,
    get_configuration_repository,
    get_discard_alert_use_case,
    get_fraud_knowledge_repository,
    get_model_repository,
    get_operational_settings_repository,
    get_optimization_run_repository,
    get_reasoning_evaluation_dispatcher,
    get_record_alert_metrics_event_use_case,
    get_record_workflow_step_metrics_use_case,
    get_search_fraud_knowledge_use_case,
    get_test_run_repository,
    get_vector_store_generation_repository,
    get_workflow_execution_repository,
    get_workflow_step_execution_repository,
    llm_step_models,
)
from src.infrastructure.workflows.celery.factories import (
    get_chat_with_agent_use_case as build_chat_with_agent_use_case,
)
from src.infrastructure.workflows.celery.factories import (
    get_orchestrate_agent_iteration_use_case as build_agent_iteration_use_case,
)
from src.infrastructure.workflows.celery.factories import (
    get_recover_stale_agent_runs_use_case as build_recover_stale_agent_runs_use_case,
)
from src.infrastructure.workflows.celery.research_adapters import (
    WorkflowVectorStoreRetriever,
)
from src.infrastructure.workflows.queued.queued_status_reporter import (
    QueuedWorkflowStatusReporter,
)

# --- task-level wiring: everything entrypoint/worker/celery/tasks.py runs ---


@lru_cache
def get_backup_catalog_repository() -> BackupCatalogRepository:
    return DynamoBackupCatalogRepository()


@lru_cache
def get_model_scoring_port() -> ModelScoringPort:
    return MCPModelScoringClient()


@lru_cache
def get_agent_shadow_observer() -> RecordAgentShadowObservation:
    return RecordAgentShadowObservation(
        releases=get_agent_release_repository(),
        components=get_agent_experiment_component_resolver(),
        scorer=get_model_scoring_port(),
        audit=get_agent_audit_repository(),
        now=get_clock().now,
    )


@lru_cache
def get_dataset_sample_repository() -> DatasetSampleRepository:
    return DynamoDatasetSampleRepository()


@lru_cache
def get_dataset_summary_repository() -> DatasetSummaryRepository:
    return DynamoDatasetSummaryRepository()


@lru_cache
def get_dataset_repository() -> MinioCsvDatasetRepository:
    return MinioCsvDatasetRepository(get_dataset_object_storage())


@lru_cache
def get_dataset_snapshot_repository() -> DynamoDatasetSnapshotRepository:
    return DynamoDatasetSnapshotRepository()


@lru_cache
def get_dataset_sampler_state_repository() -> DynamoDatasetSamplerStateRepository:
    return DynamoDatasetSamplerStateRepository()


@lru_cache
def get_mature_sampler_schema_mapping_repository() -> (
    DynamoMatureSamplerSchemaMappingRepository
):
    return DynamoMatureSamplerSchemaMappingRepository()


def get_create_mature_sample_snapshot_use_case() -> CreateMatureSampleSnapshotUseCase:
    return CreateMatureSampleSnapshotUseCase(
        alerts=get_alert_repository(),
        alert_schemas=get_alert_schema_repository(),
        operational_settings=get_operational_settings_repository(),
        sampler_settings=get_assistant_optimizer_settings_repository(),
        datasets=get_dataset_repository(),
        snapshots=get_dataset_snapshot_repository(),
        sampler_state=get_dataset_sampler_state_repository(),
        schema_mapping=get_mature_sampler_schema_mapping_repository(),
        clock=get_clock(),
    )


def get_preview_mature_sample_use_case() -> PreviewMatureSampleUseCase:
    return PreviewMatureSampleUseCase(
        alerts=get_alert_repository(),
        operational_settings=get_operational_settings_repository(),
        sampler_settings=get_assistant_optimizer_settings_repository(),
        schemas=get_alert_schema_repository(),
        sampler_state=get_dataset_sampler_state_repository(),
        schema_mapping=get_mature_sampler_schema_mapping_repository(),
        clock=get_clock(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
    )


@lru_cache
def get_alert_channel_action_port() -> MockAlertChannelActionAdapter:
    return MockAlertChannelActionAdapter()


@lru_cache
def get_async_execution_inspector() -> CeleryAsyncExecutionInspector:
    return CeleryAsyncExecutionInspector()


def get_chat_with_agent_use_case() -> ChatWithAgentUseCase:
    return build_chat_with_agent_use_case()


def get_agent_iteration_use_case() -> OrchestrateAgentIterationUseCase:
    """Task-level factory wired to the live settings repository."""
    return build_agent_iteration_use_case()


def get_agent_entity_claim_use_case():
    from src.infrastructure.workflows.celery.factories import (
        get_agent_entity_claim_use_case as build_claim_use_case,
    )

    return build_claim_use_case()


def get_recover_stale_agent_runs_use_case() -> RecoverStaleAgentRunsUseCase:
    return build_recover_stale_agent_runs_use_case()


def get_reconcile_async_operations_use_case() -> ReconcileAsyncOperationsUseCase:
    return ReconcileAsyncOperationsUseCase(
        repository=get_async_operation_repository(),
        inspector=get_async_execution_inspector(),
        workflow_repository=get_workflow_execution_repository(),
        alert_repository=get_alert_repository(),
        stuck_timeout_seconds=genai_config.CELERY_STUCK_TASK_TIMEOUT_SECONDS,
        queue_timeout_seconds=genai_config.CELERY_STUCK_QUEUE_TIMEOUT_SECONDS,
        clock=get_clock(),
    )


def get_object_storage_retention_rules() -> list[RetentionRule]:
    raw = json.loads(genai_config.OBJECT_STORAGE_RETENTION_RULES or "[]")
    return [
        RetentionRule(
            store=str(item["store"]),
            prefix=str(item["prefix"]),
            max_age_days=int(item["max_age_days"]),
        )
        for item in raw
    ]


def get_apply_object_storage_retention_use_case() -> ApplyObjectStorageRetentionUseCase:
    return ApplyObjectStorageRetentionUseCase(
        stores={
            "reports": get_object_storage(),
            "datasets": get_dataset_object_storage(),
            "models": get_model_object_storage(),
        },
        clock=get_clock(),
        protected=get_legal_hold_protected_archive_keys(),
    )


@lru_cache(maxsize=1)
def get_fraud_history_archive_index() -> ArchiveIndexPort:
    return DynamoFraudHistoryArchiveIndex()


@lru_cache(maxsize=1)
def get_legal_hold_repository() -> LegalHoldRepository:
    return DynamoLegalHoldRepository()


@lru_cache(maxsize=1)
def get_legal_hold_protected_archive_keys() -> ProtectedObjectKeysPort:
    return LegalHoldProtectedArchiveKeys(
        get_legal_hold_repository(), get_fraud_history_archive_index()
    )


@lru_cache(maxsize=1)
def get_fraud_history_archive_repository() -> FraudHistoryArchivePort:
    return DynamoFraudHistoryArchiveRepository(
        get_object_storage(),
        index=get_fraud_history_archive_index(),
        holds=get_legal_hold_repository(),
    )


@lru_cache(maxsize=1)
def get_fraud_history_archive_reader() -> FraudHistoryArchiveReaderPort:
    return DynamoFraudHistoryArchiveReader(
        get_object_storage(), get_fraud_history_archive_index()
    )


def get_archive_fraud_history_use_case() -> ArchiveFraudHistory:
    return ArchiveFraudHistory(
        get_fraud_history_archive_repository(),
        clock=get_clock(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
    )


def get_cleanup_vector_store_generations_use_case() -> (
    CleanupVectorStoreGenerationsUseCase
):
    return CleanupVectorStoreGenerationsUseCase(
        generations=get_vector_store_generation_repository(),
        configurations=get_configuration_repository(),
        deploy_requests=get_configuration_deploy_request_repository(),
        test_runs=get_test_run_repository(),
        releases=get_agent_release_repository(),
        sessions=get_agent_session_repository(),
        optimization_runs=get_optimization_run_repository(),
        fraud_knowledge_repository=get_fraud_knowledge_repository(),
        clock=get_clock(),
    )


def get_cleanup_test_runs_use_case() -> CleanupTestRunsUseCase:
    workflows = get_workflow_execution_repository()
    return CleanupTestRunsUseCase(
        list_test_runs=ListTestRunsUseCase(get_test_run_repository(), workflows),
        delete_test_runs=DeleteTestRunsUseCase(
            test_run_repository=get_test_run_repository(),
            workflow_repository=workflows,
            step_repository=get_workflow_step_execution_repository(),
            alert_repository=get_alert_repository(),
            async_operation_repository=get_async_operation_repository(),
        ),
    )


def get_agent_pipeline_replay_scorer():
    """Compose the optimizer scorer from the same worker workflow as alerts."""
    from src.infrastructure.agents.workflow_agent_pipeline_scorer import (
        WorkflowAgentPipelineScorer,
    )

    workflows = get_workflow_execution_repository()
    steps = get_workflow_step_execution_repository()
    test_runs = get_test_run_repository()
    alerts = get_alert_repository()
    operations = get_async_operation_repository()
    object_storage = get_object_storage()
    delete_test_runs = DeleteTestRunsUseCase(
        test_run_repository=test_runs,
        workflow_repository=workflows,
        step_repository=steps,
        alert_repository=alerts,
        async_operation_repository=operations,
        object_storage=object_storage,
    )
    start_test_run = StartTestRunUseCase(
        dataset_repository=get_dataset_repository(),
        test_run_repository=test_runs,
        alert_repository=alerts,
        async_operation_repository=operations,
        workflow_repository=workflows,
        workflow_executor=CeleryWorkflowExecutor(),
        configuration_repository=get_configuration_repository(),
        metrics_recorder=get_record_alert_metrics_event_use_case(),
        schema_repository=get_alert_schema_repository(),
        # The normal raw-payload lifecycle is reused; DeleteTestRunsUseCase
        # removes the temporary payload/output objects after completed replay.
        object_storage=object_storage,
        clock=get_clock(),
        id_generator=get_id_generator(),
    )
    return WorkflowAgentPipelineScorer(
        start_test_run=start_test_run,
        schemas=get_alert_schema_repository(),
        workflows=workflows,
        steps=steps,
        delete_test_runs=delete_test_runs,
        preserve_test_data=genai_config.E2E_PRESERVE_DATA,
        # Composition must remain side-effect free; the optimizer run budget
        # enforces its own timeout, so do not read DynamoDB while wiring.
        timeout_seconds=1800,
    )


def get_escalate_alert_to_analyst_use_case() -> EscalateAlertToAnalystUseCase:
    return EscalateAlertToAnalystUseCase(
        aric_alert_port=get_aric_alert_port(),
        monitoring=get_monitoring(),
    )


def get_document_analyst_decision_use_case() -> DocumentAnalystDecisionUseCase:
    return DocumentAnalystDecisionUseCase(
        llm_unit_of_work_factory=get_element_llm_factory("report"),
        monitoring=get_monitoring(),
        model=genai_config.REPORT_LLM_MODEL,
        object_storage_port=get_alert_object_storage(),
    )


def get_execute_alert_action_use_case() -> ExecuteAlertActionUseCase:
    return ExecuteAlertActionUseCase(
        alert_action_port=get_alert_channel_action_port(),
        monitoring=get_monitoring(),
    )


def get_analyze_dataset_use_case() -> AnalyzeDatasetUseCase:
    return AnalyzeDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        sample_repository=get_dataset_sample_repository(),
        summary_repository=get_dataset_summary_repository(),
        max_input_bytes=genai_config.DATASET_ANALYSIS_MAX_BYTES,
        clock=get_clock(),
    )


def get_delete_dataset_use_case() -> DeleteDatasetUseCase:
    return DeleteDatasetUseCase(
        dataset_repository=get_dataset_repository(),
        sample_repository=get_dataset_sample_repository(),
        summary_repository=get_dataset_summary_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


@lru_cache
def get_global_pipeline_evaluation_use_case() -> EvaluateGlobalPipeline:
    from src.infrastructure.workflows.celery.model_pipeline_evaluator import (
        StoredModelPipelineEvaluator,
    )

    return EvaluateGlobalPipeline(
        snapshots=get_dataset_snapshot_repository(),
        datasets=get_dataset_repository(),
        models=get_model_repository(),
        objectives=DynamoAgentObjectiveRepository(),
        verifications=get_agent_verification_repository(),
        evaluator=StoredModelPipelineEvaluator(MCPModelScoringClient()),
        clock=get_clock(),
    )


def get_analyze_fraud_marking_use_case() -> AnalyzeFraudMarkingUseCase:
    return AnalyzeFraudMarkingUseCase(
        get_dataset_repository(),
        get_dataset_summary_repository(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


# --- alert review workflow collaborators (RunAlertReviewWorkflowUseCase) ---


def get_raw_alert_payload_loader() -> RawAlertPayloadLoader:
    return RawAlertPayloadLoader(get_alert_object_storage())


def get_resolve_alert_segment_use_case() -> ResolveAlertSegmentUseCase:
    return ResolveAlertSegmentUseCase()


def get_vector_store_research_tool(
    config: VectorStoreResearchConfig,
) -> BoundedResearchTool:
    """Bounded ``search_vector_store`` tool for one configured instance."""
    if not config.vector_store_instance_id:
        raise ValueError("VECTOR_STORE_INSTANCE_ID_REQUIRED")
    return BoundedResearchTool(
        TimeBoundedResearchAgent(
            VectorStoreResearchAgent(
                WorkflowVectorStoreRetriever(
                    get_search_fraud_knowledge_use_case(),
                    config.vector_store_instance_id,
                    config.vector_store_generation,
                ),
                config,
            ),
            ResearchSource.VECTOR_STORE,
            config.timeout_seconds,
            monitoring=get_monitoring(),
        ),
        ResearchSource.VECTOR_STORE,
        max_interactions=config.max_delegations,
    )


def get_history_research_agent(
    planner: HistoryResearchPlanner,
    config: HistoryPandasResearchConfig,
    history_provider,
) -> TimeBoundedResearchAgent:
    # Lazy: the pandas-backed agent must not load with this module (the API
    # process imports it transitively and doesn't carry pandas).
    from src.infrastructure.workflows.celery.history_pandas_research import (
        HistoryPandasResearchAgent,
    )

    return TimeBoundedResearchAgent(
        HistoryPandasResearchAgent(planner, config, history_provider=history_provider),
        ResearchSource.HISTORY_PANDAS,
        config.timeout_seconds,
        monitoring=get_monitoring(),
    )


def get_research_delegation_coordinator(agents: dict) -> ResearchDelegationCoordinator:
    return ResearchDelegationCoordinator(agents)


def get_preview_features_use_case():
    # Lazy: feature engineering is only needed by the preview task.
    from src.application.use_cases.models.feature_engineering import (
        PreviewFeaturesUseCase,
    )

    return PreviewFeaturesUseCase()


def get_run_alert_review_workflow_use_case() -> RunAlertReviewWorkflowUseCase:
    # Lazy: the step modules import this module's factories at load time.
    from src.infrastructure.workflows.celery.review_step_executor import (
        CeleryWorkerStepExecutor,
    )

    workflows = get_workflow_execution_repository()
    steps = get_workflow_step_execution_repository()
    return RunAlertReviewWorkflowUseCase(
        alerts=get_alert_repository(),
        operations=get_async_operation_repository(),
        workflows=workflows,
        steps=steps,
        step_executor=CeleryWorkerStepExecutor(),
        # One reporter (and its writer thread) per run, never shared.
        status_reporter_factory=lambda: QueuedWorkflowStatusReporter(workflows, steps),
        escalation=get_analyst_escalation_dispatcher(),
        documenter=get_analyst_decision_documenter(),
        reasoning_evaluation=get_reasoning_evaluation_dispatcher(),
        operational_settings=get_operational_settings_repository(),
        monitoring=get_monitoring(),
        discard_alert=get_discard_alert_use_case(),
        record_metrics_event=get_record_alert_metrics_event_use_case(),
        record_step_metrics=get_record_workflow_step_metrics_use_case(),
        step_models=llm_step_models,
        raw_payload_loader_factory=get_raw_alert_payload_loader,
        alert_schemas_factory=get_alert_schema_repository,
        alert_object_storage_factory=get_alert_object_storage,
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_start_production_alert_workflow_use_case() -> StartAlertTestWorkflowUseCase:
    return StartAlertTestWorkflowUseCase(
        alert_repository=get_alert_repository(),
        async_operation_repository=get_async_operation_repository(),
        workflow_repository=get_workflow_execution_repository(),
        workflow_executor=CeleryWorkflowExecutor(),
        clock=get_clock(),
        id_generator=get_id_generator(),
    )


def get_worker_retrospective_validation_use_case():
    """Retrospective validation that replays the real alert pipeline."""
    from src.application.use_cases.agent.paired_agent_experiment_runner import (
        PairedAgentExperimentRunner,
    )
    from src.application.use_cases.agent.validate_retrospective_release import (
        ValidateRetrospectiveReleaseUseCase,
    )
    from src.infrastructure.agents.factories import (
        get_agent_audit_repository,
        get_agent_experiment_component_resolver,
        get_agent_experiment_repository,
        get_agent_objective_repository,
        get_agent_release_repository,
    )

    objectives = get_agent_objective_repository()
    return ValidateRetrospectiveReleaseUseCase(
        experiments=get_agent_experiment_repository(),
        releases=get_agent_release_repository(),
        snapshots=get_dataset_snapshot_repository(),
        datasets=get_dataset_repository(),
        objectives=objectives,
        evaluator=PairedAgentExperimentRunner(
            components=get_agent_experiment_component_resolver(),
            scorer=get_agent_pipeline_replay_scorer(),
            objectives=objectives,
        ),
        audit=get_agent_audit_repository(),
        now=get_clock().now,
        new_id=lambda: str(get_id_generator().new_id()),
    )
