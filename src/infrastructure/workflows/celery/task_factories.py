from __future__ import annotations

import json
from functools import lru_cache

from src.application.dtos.research_dtos import ResearchSource
from src.application.ports.backup_catalog_port import BackupCatalogRepository
from src.application.ports.dataset_analysis_port import DatasetSampleRepository
from src.application.ports.dataset_summary_port import DatasetSummaryRepository
from src.application.ports.history_research_planner_port import HistoryResearchPlanner
from src.application.ports.model_scoring_port import ModelScoringPort
from src.application.use_cases.agent.orchestrate_agent_iteration import (
    OrchestrateAgentIterationUseCase,
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
from src.domain.configurations.entities import (
    HistoryPandasResearchConfig,
    VectorStoreResearchConfig,
)
from src.infrastructure.alert_actions.mock.alert_channel_action_adapter import (
    MockAlertChannelActionAdapter,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.core.runtime.uuid_generator import get_id_generator
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.model_serving.mcp_scoring_client import (
    MCPModelScoringClient,
)
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.backup_catalog_repository import (
    DynamoBackupCatalogRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_sample_repository import (
    DynamoDatasetSampleRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.dataset_summary_repository import (
    DynamoDatasetSummaryRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.mature_sample_repository import (
    DynamoDatasetSamplerStateRepository,
    DynamoDatasetSnapshotRepository,
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
from src.infrastructure.workflows.celery.factories import (
    get_alert_object_storage,
    get_alert_repository,
    get_alert_schema_repository,
    get_analyst_decision_documenter,
    get_analyst_escalation_dispatcher,
    get_aric_alert_port,
    get_assistant_optimizer_settings_repository,
    get_async_operation_repository,
    get_discard_alert_use_case,
    get_operational_settings_repository,
    get_reasoning_evaluation_dispatcher,
    get_record_alert_metrics_event_use_case,
    get_record_workflow_step_metrics_use_case,
    get_search_fraud_knowledge_use_case,
    get_test_run_repository,
    get_workflow_execution_repository,
    get_workflow_step_execution_repository,
    llm_step_models,
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


def get_create_mature_sample_snapshot_use_case() -> CreateMatureSampleSnapshotUseCase:
    return CreateMatureSampleSnapshotUseCase(
        alerts=get_alert_repository(),
        alert_schemas=get_alert_schema_repository(),
        operational_settings=get_operational_settings_repository(),
        sampler_settings=get_assistant_optimizer_settings_repository(),
        datasets=get_dataset_repository(),
        snapshots=get_dataset_snapshot_repository(),
        sampler_state=get_dataset_sampler_state_repository(),
        clock=get_clock(),
    )


def get_preview_mature_sample_use_case() -> PreviewMatureSampleUseCase:
    return PreviewMatureSampleUseCase(
        alerts=get_alert_repository(),
        operational_settings=get_operational_settings_repository(),
        sampler_settings=get_assistant_optimizer_settings_repository(),
        schemas=get_alert_schema_repository(),
        sampler_state=get_dataset_sampler_state_repository(),
        clock=get_clock(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
    )


@lru_cache
def get_alert_channel_action_port() -> MockAlertChannelActionAdapter:
    return MockAlertChannelActionAdapter()


@lru_cache
def get_async_execution_inspector() -> CeleryAsyncExecutionInspector:
    return CeleryAsyncExecutionInspector()


def get_agent_iteration_use_case() -> OrchestrateAgentIterationUseCase:
    """Task-level factory wired to the live settings repository."""
    return build_agent_iteration_use_case()


def get_recover_stale_agent_runs_use_case() -> RecoverStaleAgentRunsUseCase:
    return build_recover_stale_agent_runs_use_case()


def get_reconcile_async_operations_use_case() -> ReconcileAsyncOperationsUseCase:
    return ReconcileAsyncOperationsUseCase(
        repository=get_async_operation_repository(),
        inspector=get_async_execution_inspector(),
        workflow_repository=get_workflow_execution_repository(),
        alert_repository=get_alert_repository(),
        stuck_timeout_seconds=genai_config.CELERY_STUCK_TASK_TIMEOUT_SECONDS,
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


def get_escalate_alert_to_analyst_use_case() -> EscalateAlertToAnalystUseCase:
    return EscalateAlertToAnalystUseCase(
        aric_alert_port=get_aric_alert_port(),
        monitoring=get_monitoring(),
    )


def get_document_analyst_decision_use_case() -> DocumentAnalystDecisionUseCase:
    return DocumentAnalystDecisionUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
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
    return BoundedResearchTool(
        TimeBoundedResearchAgent(
            VectorStoreResearchAgent(
                WorkflowVectorStoreRetriever(
                    get_search_fraud_knowledge_use_case(),
                    config.vector_store_instance_id,
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
