from __future__ import annotations

import json

from src.application.dtos.document_analyst_decision_dtos import (
    DocumentAnalystDecisionInput,
    DocumentAnalystDecisionOutput,
)
from src.application.ports.llm_unit_of_work_port import (
    LLMMessage,
    LLMMessageRole,
    LLMUnitOfWorkFactory,
)
from src.application.ports.monitoring_port import MonitoringPort
from src.application.ports.object_storage_port import ObjectStoragePort

_SYSTEM_PROMPT = (
    "You are a fraud operations report writer. You are given the raw "
    "step-by-step data of a fraud alert review pipeline: pre-processing, "
    "profiling, classification, adversarial review, and the analyst's "
    "final decision. Paraphrase this data into a clear, well-formatted "
    "Markdown report for a human reader (a fraud operations lead). Use a "
    "heading per stage present in the data, in the order given, and close "
    "with a short summary of the analyst's decision and why. Only "
    "paraphrase what is in the data - never invent facts, numbers, or "
    "outcomes not present in it."
)

_USER_PROMPT = "Pipeline step data:\n{data}"


class DocumentAnalystDecisionUseCase:
    def __init__(
        self,
        llm_unit_of_work_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
        object_storage_port: ObjectStoragePort,
    ) -> None:
        self._llm_factory = llm_unit_of_work_factory
        self._monitoring = monitoring
        self._model = model
        self._object_storage_port = object_storage_port

    def execute(
        self, input: DocumentAnalystDecisionInput
    ) -> DocumentAnalystDecisionOutput:
        uow = self._llm_factory.create(
            model=self._model,
            monitoring=self._monitoring,
            operation_name="document_analyst_decision",
        )
        result = uow.invoke(
            [
                LLMMessage(role=LLMMessageRole.SYSTEM, content=_SYSTEM_PROMPT),
                LLMMessage(
                    role=LLMMessageRole.USER,
                    content=_USER_PROMPT.format(
                        data=json.dumps(input.steps, default=str)
                    ),
                ),
            ]
        )
        report = result.content
        key = (
            f"alerts/{input.alert_id}/{input.workflow_execution_id}/"
            "analyst_report.md"
        )
        ref = self._object_storage_port.put_text(
            key, report, content_type="text/markdown"
        )
        return DocumentAnalystDecisionOutput(report=report, object_storage_ref=ref)
