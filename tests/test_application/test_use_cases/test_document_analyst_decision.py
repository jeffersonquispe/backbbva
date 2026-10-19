from __future__ import annotations

import uuid

from src.application.dtos.document_analyst_decision_dtos import (
    DocumentAnalystDecisionInput,
)
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.monitoring_span_port import MonitoringSpan
from src.application.ports.object_storage_port import (
    ObjectStoragePort,
    ObjectStorageRef,
)
from src.application.use_cases.alerts.document_analyst_decision import (
    DocumentAnalystDecisionUseCase,
)


class ScriptedLLMUnitOfWork(LLMUnitOfWork):
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.received_messages: list[list[LLMMessage]] = []

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        self.received_messages.append(list(messages))
        content = self._responses.pop(0)
        return LLMInvocationResult(content=content, model="fake-model")


class ScriptedLLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.created: list[ScriptedLLMUnitOfWork] = []
        self.operation_names: list[str] = []

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        self.operation_names.append(operation_name)
        uow = ScriptedLLMUnitOfWork(self._responses)
        self.created.append(uow)
        return uow


class NullSpan(MonitoringSpan):
    def write_input(self, data) -> None:
        pass

    def write_result(self, data) -> None:
        pass

    def write_inner_logs(self, entries) -> None:
        pass

    def write_operation_metas(self, metadata) -> None:
        pass

    def record_dependency(self, name, kind, metadata=None) -> None:
        pass

    def finish(self, error=None) -> None:
        pass


class NullMonitoringPort(MonitoringPort):
    def start(self, operation_name, operation_type, metadata=None) -> MonitoringSpan:
        return NullSpan()


class RecordingObjectStoragePort(ObjectStoragePort):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def put_text(
        self,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> ObjectStorageRef:
        self.calls.append((key, content, content_type))
        return ObjectStorageRef(
            bucket="aria-reports", key=key, uri=f"s3://aria-reports/{key}"
        )


def test_document_analyst_decision_stores_llm_report() -> None:
    responses = ["# Alert Review Report\n\nThe alert was classified as fraud."]
    llm_factory = ScriptedLLMUnitOfWorkFactory(responses)
    storage = RecordingObjectStoragePort()
    use_case = DocumentAnalystDecisionUseCase(
        llm_unit_of_work_factory=llm_factory,
        monitoring=NullMonitoringPort(),
        model="fake-deployment",
        object_storage_port=storage,
    )
    alert_id = uuid.uuid4()
    workflow_execution_id = uuid.uuid4()

    output = use_case.execute(
        DocumentAnalystDecisionInput(
            alert_id=alert_id,
            workflow_execution_id=workflow_execution_id,
            steps={
                "classification": {
                    "is_fraud": "fraud",
                    "fraud_classification": "ACCOUNT_TAKEOVER",
                    "reasoning": "matches known pattern",
                },
                "analyst": {"decision": "block", "reasoning": "confirmed fraud"},
            },
        )
    )

    assert (
        output.report == "# Alert Review Report\n\nThe alert was classified as fraud."
    )
    assert output.object_storage_ref.uri == (
        f"s3://aria-reports/alerts/{alert_id}/{workflow_execution_id}/analyst_report.md"
    )
    assert len(storage.calls) == 1
    key, content, content_type = storage.calls[0]
    assert key == f"alerts/{alert_id}/{workflow_execution_id}/analyst_report.md"
    assert content == output.report
    assert content_type == "text/markdown"
    assert llm_factory.operation_names == ["document_analyst_decision"]
