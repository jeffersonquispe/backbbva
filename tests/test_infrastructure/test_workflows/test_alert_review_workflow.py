from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import src.infrastructure.workflows.celery.alert_review_workflow as workflow_module
import src.infrastructure.workflows.celery.factories as factories_module
from src.application.ports.alert_action_dispatcher_port import (
    AlertActionDispatchRef,
    AlertActionDispatcher,
)
from src.application.ports.alert_port import AlertRecord, AlertStatus
from src.application.ports.analyst_decision_documenter_port import (
    AnalystDecisionDocumenter,
    DocumentationDispatchRef,
)
from src.application.ports.analyst_escalation_port import (
    AnalystEscalationDispatcher,
    AnalystEscalationRef,
)
from src.application.ports.async_operation_port import (
    AsyncOperationRecord,
    AsyncOperationStatus,
)
from src.application.ports.configuration_port import (
    AgentSettings,
    ConfigurationRecord,
    DeterministicConfig,
    DeterministicRule,
    FilterGroup,
    GeneralSettings,
    InfraSettings,
    OpsSettings,
    SegmentSettings,
    TestSettings,
)
from src.application.ports.fraud_playbook_port import FraudPlaybookRecord
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.operations_capacity_port import (
    ChannelCapacity,
    OperationsCapacityRecord,
)
from src.application.ports.workflow_port import (
    WorkflowExecutionRecord,
    WorkflowStatus,
    WorkflowStepExecutionRecord,
    WorkflowStepStatus,
)
from src.infrastructure.monitoring.opentelemetry.monitoring import (
    OpenTelemetryMonitoring,
)
from src.infrastructure.workflows.celery.alert_review_workflow import (
    AlertReviewWorkflowRunner,
)

# Same mandatory-field shape as tests/test_application/test_use_cases/
# test_pre_process_alert.py's VALID_PAYLOAD - non-card channel, every
# dotted path pre_process_alert.py's _MANDATORY_FIELD_PATHS requires.
SYNTHETIC_ALERT_PAYLOAD = {
    "eventId": "evt-synth-1",
    "eventType": "paymentRT",
    "eventTime": "2026-08-09T10:00:00Z",
    "customerId": "10264559",
    "accountId": "acct-synth-1",
    "channel": "mobileApp",
    "merchantId": "merch-synth-1",
    "merchantName": "Synthetic Merchant SAS",
    "integrationPoint": "APP",
    "serviceDescription": "Online transfer",
    "msgStatus": "APPROVED",
    "direction": "OUT",
    "msgReason": "none",
    "customerClientCode": "CC-synth-1",
    "object": {
        "triggeredRules": [{"name": "rule1"}],
        "tags": [{"values": ["high_value"]}],
        "triggeredModels": ["model1"],
    },
    "biocatch": {
        "score": 10,
        "ip": "1.2.3.4",
        "muid": "muid-1",
        "customerSessionID": "sess-synth-1",
    },
    "entryMode": {"terminalDataInputModeCapability": "manual"},
    "session": {"sessionId": "sess-synth-1"},
    "counterpartyName": {"fullName": "Jane Synthetic Doe"},
    "amount": {"baseValue": 15_000_000.0},
    "device": {"ipAddress": "5.6.7.8", "userAgentString": "Mozilla/5.0 (synthetic)"},
    "_metadata": {"searchable": {"deviceId": "dev-synth-1"}},
    "personalId": "pid-synth-1",
}


class InMemoryAlertRepository:
    def __init__(self) -> None:
        self.alerts: dict[UUID, AlertRecord] = {}

    def create(self, alert: AlertRecord) -> AlertRecord:
        self.alerts[alert.id] = alert
        return alert

    def get(self, alert_id: UUID) -> AlertRecord | None:
        return self.alerts.get(alert_id)

    def update(self, alert_id: UUID, **changes: Any) -> AlertRecord | None:
        alert = self.alerts.get(alert_id)
        if alert is None:
            return None
        updated = dataclasses.replace(
            alert, **{k: v for k, v in changes.items() if v is not None}
        )
        self.alerts[alert_id] = updated
        return updated


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations: dict[UUID, AsyncOperationRecord] = {}

    def create(self, operation: AsyncOperationRecord) -> AsyncOperationRecord:
        self.operations[operation.id] = operation
        return operation

    def get(self, operation_id: UUID) -> AsyncOperationRecord | None:
        return self.operations.get(operation_id)

    def list(
        self, status: AsyncOperationStatus | None = None, limit: int = 100
    ) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def list_active(self, limit: int = 100) -> list[AsyncOperationRecord]:
        return list(self.operations.values())[:limit]

    def update(self, operation_id: UUID, **changes: Any) -> AsyncOperationRecord | None:
        operation = self.operations.get(operation_id)
        if operation is None:
            return None
        updated = dataclasses.replace(
            operation, **{k: v for k, v in changes.items() if v is not None}
        )
        self.operations[operation_id] = updated
        return updated


class InMemoryWorkflowExecutionRepository:
    def __init__(self) -> None:
        self.workflows: dict[UUID, WorkflowExecutionRecord] = {}

    def create(self, workflow: WorkflowExecutionRecord) -> WorkflowExecutionRecord:
        self.workflows[workflow.id] = workflow
        return workflow

    def get(self, workflow_id: UUID) -> WorkflowExecutionRecord | None:
        return self.workflows.get(workflow_id)

    def update(
        self, workflow_id: UUID, **changes: Any
    ) -> WorkflowExecutionRecord | None:
        workflow = self.workflows.get(workflow_id)
        if workflow is None:
            return None
        updated = dataclasses.replace(
            workflow, **{k: v for k, v in changes.items() if v is not None}
        )
        self.workflows[workflow_id] = updated
        return updated


class InMemoryWorkflowStepExecutionRepository:
    def __init__(self) -> None:
        self.steps: dict[UUID, WorkflowStepExecutionRecord] = {}

    def create(self, step: WorkflowStepExecutionRecord) -> WorkflowStepExecutionRecord:
        self.steps[step.id] = step
        return step

    def list_by_workflow(
        self, workflow_execution_id: UUID
    ) -> list[WorkflowStepExecutionRecord]:
        return [
            step
            for step in self.steps.values()
            if step.workflow_execution_id == workflow_execution_id
        ]

    def update(
        self, workflow_execution_id: UUID, step_id: UUID, **changes: Any
    ) -> WorkflowStepExecutionRecord | None:
        step = self.steps.get(step_id)
        if step is None:
            return None
        updated = dataclasses.replace(
            step, **{k: v for k, v in changes.items() if v is not None}
        )
        self.steps[step_id] = updated
        return updated


class InMemoryConfigurationRepository:
    """Only get_active() is implemented - the only method
    _resolve_configuration calls on the no-ref (production) path."""

    def __init__(self, active: ConfigurationRecord | None) -> None:
        self._active = active

    def get_active(self) -> ConfigurationRecord | None:
        return self._active


class InMemoryFraudPlaybookRepository:
    def __init__(self, playbooks: list[FraudPlaybookRecord]) -> None:
        self._playbooks = {p.classification: p for p in playbooks}

    def create(self, playbook: FraudPlaybookRecord) -> FraudPlaybookRecord:
        self._playbooks[playbook.classification] = playbook
        return playbook

    def get(self, classification: str) -> FraudPlaybookRecord | None:
        return self._playbooks.get(classification)

    def update(self, classification: str, **changes: Any) -> FraudPlaybookRecord | None:
        raise NotImplementedError

    def list(self) -> list[FraudPlaybookRecord]:
        return list(self._playbooks.values())


class InMemoryOperationsCapacityRepository:
    def __init__(self, capacity: OperationsCapacityRecord) -> None:
        self._capacity = capacity

    def get_capacity(self) -> OperationsCapacityRecord:
        return self._capacity


class RecordingAlertActionDispatcher(AlertActionDispatcher):
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID, str | None]] = []

    def dispatch(
        self, action: str, alert_id: UUID, content: str | None = None
    ) -> AlertActionDispatchRef:
        self.calls.append((action, alert_id, content))
        return AlertActionDispatchRef(backend="celery", external_id="fake-action-1")


class RecordingAnalystEscalationDispatcher(AnalystEscalationDispatcher):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        event_id: str,
        session_id: str | None,
        reason: str,
    ) -> AnalystEscalationRef:
        self.calls.append(
            {
                "alert_id": alert_id,
                "workflow_execution_id": workflow_execution_id,
                "event_id": event_id,
                "session_id": session_id,
                "reason": reason,
            }
        )
        return AnalystEscalationRef(backend="celery", external_id="fake-escalation-1")


class RecordingAnalystDecisionDocumenter(AnalystDecisionDocumenter):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def dispatch(
        self,
        alert_id: UUID,
        workflow_execution_id: UUID,
        steps: dict[str, dict[str, Any]],
    ) -> DocumentationDispatchRef:
        self.calls.append(
            {
                "alert_id": alert_id,
                "workflow_execution_id": workflow_execution_id,
                "steps": steps,
            }
        )
        return DocumentationDispatchRef(backend="celery", external_id="fake-doc-1")


# One canned final answer per ReAct/JSON operation_name - each use case's
# system prompt asks for a single well-formed "Final Answer:"/JSON turn, so
# the fake never needs to emit a Thought/Action step to stay deterministic.
_LLM_RESPONSES: dict[str, str] = {
    "user_profile": (
        "Synthetic user profile: long-standing customer, no adverse "
        "behavioral signals on record."
    ),
    "transaction_profile": (
        "Synthetic transaction profile: amount and channel are within "
        "this account's historical norms."
    ),
    "transactional_profile": (
        "Synthetic transactional profile: consistent with the customer's "
        "prior 90-day transaction pattern."
    ),
    "classification": (
        "Thought: device and session signals diverge from prior sessions.\n"
        'Final Answer: {"is_fraud": "fraud", "fraud_classification": '
        '"account_takeover", "reasoning": "Session and device fingerprint '
        'are inconsistent with the known customer profile."}'
    ),
    "adversarial": (
        "Thought: independently checked the analyst's evidence.\n"
        'Final Answer: {"has_issues": false, "feedback": "", '
        '"weak_points": [], "reasoning": "Classification is well '
        'supported by the available evidence."}'
    ),
    "analyst": (
        '{"decision": "bidi", "reasoning": "Moderate risk and bidi '
        'channel has available capacity - route for verification."}'
    ),
}


class FakeLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self, operation_name: str) -> None:
        self._operation_name = operation_name

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        return LLMInvocationResult(
            content=_LLM_RESPONSES[self._operation_name],
            model="fake-model",
        )


class FakeLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        self.calls.append(operation_name)
        return FakeLLMUnitOfWork(operation_name)


def _build_in_memory_monitoring() -> tuple[MonitoringPort, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OpenTelemetryMonitoring(provider.get_tracer("test")), exporter


def test_alert_review_workflow_runs_full_pipeline_on_synthetic_alert(monkeypatch):
    now = datetime.now(timezone.utc)

    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    playbooks = InMemoryFraudPlaybookRepository(
        [
            FraudPlaybookRecord(
                classification="account_takeover",
                title="Account Takeover Playbook",
                steps=["Verify device fingerprint", "Contact customer via bidi"],
                created_at=now,
                updated_at=now,
            )
        ]
    )
    capacity = InMemoryOperationsCapacityRepository(
        OperationsCapacityRecord(
            analysts=ChannelCapacity(available=3, status="available"),
            voicebot=ChannelCapacity(available=2, status="available"),
            bidi=ChannelCapacity(available=1, status="available"),
            updated_at=now,
        )
    )
    action_dispatcher = RecordingAlertActionDispatcher()
    escalation_dispatcher = RecordingAnalystEscalationDispatcher()
    documenter_dispatcher = RecordingAnalystDecisionDocumenter()
    llm_factory = FakeLLMUnitOfWorkFactory()
    # Only used so real step use cases get a real MonitoringPort instance
    # (type-correct DI) - FakeLLMUnitOfWork never calls monitoring.start(),
    # unlike the real Langchain adapter, so no spans land here to assert on.
    monitoring, _ = _build_in_memory_monitoring()

    # AlertReviewWorkflowRunner and the per-step _run_* functions call these
    # factory functions by the name each imported into its own module
    # namespace, so patches must target the module that does the calling:
    # workflow_module for repos/dispatchers it calls directly, factories_module
    # for adapters only ever looked up from inside a get_*_use_case() factory.
    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(
        workflow_module, "get_async_operation_repository", lambda: operations
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_execution_repository", lambda: workflows
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_step_execution_repository", lambda: steps
    )
    monkeypatch.setattr(
        factories_module, "get_fraud_playbook_repository", lambda: playbooks
    )
    monkeypatch.setattr(
        factories_module, "get_operations_capacity_repository", lambda: capacity
    )
    monkeypatch.setattr(
        workflow_module, "get_alert_action_dispatcher", lambda: action_dispatcher
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_escalation_dispatcher",
        lambda: escalation_dispatcher,
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_decision_documenter",
        lambda: documenter_dispatcher,
    )
    monkeypatch.setattr(
        factories_module, "get_llm_unit_of_work_factory", lambda: llm_factory
    )
    monkeypatch.setattr(factories_module, "get_monitoring", lambda: monitoring)

    alert_id = uuid.uuid4()
    async_operation_id = uuid.uuid4()
    workflow_id = uuid.uuid4()

    alerts.create(
        AlertRecord(
            id=alert_id,
            event_id=SYNTHETIC_ALERT_PAYLOAD["eventId"],
            event_type=SYNTHETIC_ALERT_PAYLOAD["eventType"],
            payload=SYNTHETIC_ALERT_PAYLOAD,
            status=AlertStatus.PROCESSING,
            created_at=now,
            updated_at=now,
            customer_id=SYNTHETIC_ALERT_PAYLOAD["customerId"],
            async_operation_id=async_operation_id,
            workflow_execution_id=workflow_id,
        )
    )
    operations.create(
        AsyncOperationRecord(
            id=async_operation_id,
            operation_type="alert_review_workflow",
            status=AsyncOperationStatus.DISPATCHED,
            payload={"alert_id": str(alert_id)},
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
    )
    workflows.create(
        WorkflowExecutionRecord(
            id=workflow_id,
            alert_id=alert_id,
            async_operation_id=async_operation_id,
            workflow_name="alert_review",
            status=WorkflowStatus.PENDING,
            input={"alert_payload": SYNTHETIC_ALERT_PAYLOAD},
            output=None,
            error=None,
            current_step=None,
            feedback_iterations=0,
            max_feedback_iterations=2,
            created_at=now,
            updated_at=now,
        )
    )

    result = AlertReviewWorkflowRunner().run(workflow_id)

    assert result == {"status": "ok", "workflow_execution_id": str(workflow_id)}

    finished_workflow = workflows.get(workflow_id)
    assert finished_workflow is not None
    assert finished_workflow.status == WorkflowStatus.SUCCEEDED
    assert finished_workflow.current_step == "post_process"
    assert finished_workflow.output is not None
    assert finished_workflow.output["resolution_path"] == "bidi"

    finished_alert = alerts.get(alert_id)
    assert finished_alert is not None
    assert finished_alert.status == AlertStatus.CLOSED

    finished_operation = operations.get(async_operation_id)
    assert finished_operation is not None
    assert finished_operation.status == AsyncOperationStatus.SUCCEEDED

    recorded_steps = {s.step_name: s for s in steps.list_by_workflow(workflow_id)}
    assert set(recorded_steps) == {
        "pre_process",
        "deterministic",
        "profiling",
        "classification",
        "adversarial",
        "analyst",
        "executor",
        "post_process",
    }
    assert all(
        step.status == WorkflowStepStatus.SUCCEEDED
        for step in recorded_steps.values()
    )
    assert recorded_steps["classification"].output["fraud_classification"] == (
        "account_takeover"
    )
    assert recorded_steps["analyst"].output["decision"] == "bidi"

    # No active configuration/segment in this synthetic run, so there's no
    # executor.aric_marking prompt to generate a comment from - content
    # stays None (see alert_review_workflow.py's _run_executor).
    assert action_dispatcher.calls == [("bidi", alert_id, None)]
    assert escalation_dispatcher.calls == []
    assert len(documenter_dispatcher.calls) == 1
    assert set(documenter_dispatcher.calls[0]["steps"]) == {
        "pre_process",
        "profiling",
        "classification",
        "adversarial",
        "analyst",
    }

    assert llm_factory.calls == [
        "user_profile",
        "transaction_profile",
        "transactional_profile",
        "classification",
        "adversarial",
        "analyst",
    ]


def test_alert_review_workflow_discards_alert_on_deterministic_rule_match(monkeypatch):
    now = datetime.now(timezone.utc)

    alerts = InMemoryAlertRepository()
    operations = InMemoryAsyncOperationRepository()
    workflows = InMemoryWorkflowExecutionRepository()
    steps = InMemoryWorkflowStepExecutionRepository()
    action_dispatcher = RecordingAlertActionDispatcher()
    escalation_dispatcher = RecordingAnalystEscalationDispatcher()
    documenter_dispatcher = RecordingAnalystDecisionDocumenter()
    llm_factory = FakeLLMUnitOfWorkFactory()
    monitoring, exporter = _build_in_memory_monitoring()

    # A single enabled segment with an empty filter (vacuously matches any
    # alert - see resolve_alert_segment.py) and one deterministic rule that
    # matches SYNTHETIC_ALERT_PAYLOAD's amount (15_000_000).
    segment = SegmentSettings(
        enabled=True,
        filter=FilterGroup(id="root"),
        agent=AgentSettings(
            deterministic=DeterministicConfig(
                rules=[
                    DeterministicRule(
                        id="high-amount",
                        variable="amount",
                        comparison="gt",
                        values=["1000000"],
                        decision="risk",
                        aric_action="hard_block",
                    )
                ]
            )
        ),
    )
    config_repo = InMemoryConfigurationRepository(
        ConfigurationRecord(
            configuration_id="cfg-discard",
            version=1,
            name="cfg-discard-v1",
            description="",
            active=True,
            general=GeneralSettings(),
            infra=InfraSettings(),
            ops=OpsSettings(),
            test=TestSettings(),
            created_at=now,
            updated_at=now,
            segments={"canales_digitales": segment},
        )
    )

    monkeypatch.setattr(workflow_module, "get_alert_repository", lambda: alerts)
    monkeypatch.setattr(
        workflow_module, "get_async_operation_repository", lambda: operations
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_execution_repository", lambda: workflows
    )
    monkeypatch.setattr(
        workflow_module, "get_workflow_step_execution_repository", lambda: steps
    )
    monkeypatch.setattr(
        workflow_module, "get_configuration_repository", lambda: config_repo
    )
    monkeypatch.setattr(
        workflow_module, "get_alert_action_dispatcher", lambda: action_dispatcher
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_escalation_dispatcher",
        lambda: escalation_dispatcher,
    )
    monkeypatch.setattr(
        workflow_module,
        "get_analyst_decision_documenter",
        lambda: documenter_dispatcher,
    )
    monkeypatch.setattr(
        factories_module, "get_llm_unit_of_work_factory", lambda: llm_factory
    )
    monkeypatch.setattr(factories_module, "get_monitoring", lambda: monitoring)

    alert_id = uuid.uuid4()
    async_operation_id = uuid.uuid4()
    workflow_id = uuid.uuid4()

    alerts.create(
        AlertRecord(
            id=alert_id,
            event_id=SYNTHETIC_ALERT_PAYLOAD["eventId"],
            event_type=SYNTHETIC_ALERT_PAYLOAD["eventType"],
            payload=SYNTHETIC_ALERT_PAYLOAD,
            status=AlertStatus.PROCESSING,
            created_at=now,
            updated_at=now,
            customer_id=SYNTHETIC_ALERT_PAYLOAD["customerId"],
            async_operation_id=async_operation_id,
            workflow_execution_id=workflow_id,
        )
    )
    operations.create(
        AsyncOperationRecord(
            id=async_operation_id,
            operation_type="alert_review_workflow",
            status=AsyncOperationStatus.DISPATCHED,
            payload={"alert_id": str(alert_id)},
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
    )
    workflows.create(
        WorkflowExecutionRecord(
            id=workflow_id,
            alert_id=alert_id,
            async_operation_id=async_operation_id,
            workflow_name="alert_review",
            status=WorkflowStatus.PENDING,
            input={"alert_payload": SYNTHETIC_ALERT_PAYLOAD},
            output=None,
            error=None,
            current_step=None,
            feedback_iterations=0,
            max_feedback_iterations=2,
            created_at=now,
            updated_at=now,
        )
    )

    result = AlertReviewWorkflowRunner().run(workflow_id)

    assert result == {"status": "ok", "workflow_execution_id": str(workflow_id)}

    finished_workflow = workflows.get(workflow_id)
    assert finished_workflow is not None
    assert finished_workflow.status == WorkflowStatus.SUCCEEDED
    assert finished_workflow.current_step == "deterministic"
    assert finished_workflow.output is not None
    assert finished_workflow.output["resolution_path"] == "discarded_deterministic"

    finished_alert = alerts.get(alert_id)
    assert finished_alert is not None
    assert finished_alert.status == AlertStatus.CLOSED

    # Only pre_process and deterministic ran - everything from profiling
    # onward was skipped.
    recorded_steps = {s.step_name for s in steps.list_by_workflow(workflow_id)}
    assert recorded_steps == {"pre_process", "deterministic"}

    assert action_dispatcher.calls == []
    assert escalation_dispatcher.calls == []
    assert documenter_dispatcher.calls == []
    assert llm_factory.calls == []

    spans = exporter.get_finished_spans()
    discard_spans = [s for s in spans if s.name == "discard_alert"]
    assert len(discard_spans) == 1
