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
    "Eres un redactor de reportes de operaciones de fraude. Se te entregan "
    "los datos crudos, paso a paso, de un pipeline de revisión de alertas "
    "de fraude: pre-procesamiento, perfilamiento, clasificación, revisión "
    "adversarial y la decisión final del analista. Parafrasea estos datos "
    "en un reporte claro y bien formateado en Markdown, escrito en "
    "español, para un lector humano (un líder de operaciones de fraude). "
    "Usa un encabezado por cada etapa presente en los datos, en el orden "
    "dado, y cierra con un resumen breve de la decisión del analista y su "
    "razón. Parafrasea únicamente lo que está en los datos - nunca "
    "inventes hechos, cifras o resultados que no estén presentes en ellos."
)

_USER_PROMPT = "Datos del pipeline por etapa:\n{data}"


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
