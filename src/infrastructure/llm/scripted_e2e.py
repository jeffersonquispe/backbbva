"""Deterministic local LLM adapter for end-to-end workflow verification."""

from __future__ import annotations

import json

from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import (
    LLMInvocationResult,
    LLMMessage,
    LLMUnitOfWork,
)
from src.application.ports.monitoring_port import MonitoringPort


class ScriptedE2ELLMUnitOfWorkFactory(LLMUnitOfWorkFactory):
    """Returns stable outputs for workflow LLM operations in local E2E runs."""

    def create(
        self,
        *,
        model: str,
        monitoring: MonitoringPort,
        operation_name: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMUnitOfWork:
        del temperature, max_tokens
        return _ScriptedE2ELLMUnitOfWork(model, operation_name, monitoring)


class _ScriptedE2ELLMUnitOfWork(LLMUnitOfWork):
    def __init__(
        self, model: str, operation_name: str, monitoring: MonitoringPort
    ) -> None:
        self._model = model
        self._operation_name = operation_name
        self._monitoring = monitoring

    def invoke(self, messages: list[LLMMessage]) -> LLMInvocationResult:
        operation = self._operation_name
        if operation in {"detector", "classification"}:
            content = (
                "Thought: El fixture de prueba presenta cinco transferencias "
                "PSE al mismo beneficiario en diez minutos; deviceid está "
                "presente y las señales RAT son negativas.\n"
                'Final Answer: {"is_fraud":"fraud",'
                '"fraud_classification":"transfer_velocity",'
                '"reasoning":"Cinco transferencias PSE al mismo beneficiario '
                'en diez minutos; deviceid presente y señales RAT negativas."}'
            )
        elif operation in {"detector_adversarial", "adversarial"}:
            content = (
                "Thought: La conclusión es coherente con la evidencia y no "
                "afirma causas no observadas.\n"
                'Final Answer: {"has_issues":false,"feedback":"",'
                '"weak_points":[],"reasoning":"La etiqueta transfer_velocity '
                'es consistente con el evento."}'
            )
        elif operation == "analyst":
            content = json.dumps(
                {
                    "decision": "scale_to_analyst",
                    "reasoning": "Revisión humana requerida por patrón de velocidad.",
                }
            )
        elif operation in {
            "user_profile",
            "transaction_profile",
            "transactional_profile",
        }:
            content = "Perfil generado por el adaptador determinista E2E local."
        else:
            content = "Documentación E2E local de la decisión de fraude."
        with self._monitoring.start(
            operation,
            "llm",
            metadata={
                "operation_name": operation,
                "provider": "scripted_e2e",
                "model": self._model,
            },
        ) as span:
            span.write_input(
                {
                    "messages": [
                        {"role": item.role.value, "content": item.content}
                        for item in messages
                    ]
                }
            )
            result = LLMInvocationResult(
                content=content,
                model=self._model,
                finish_reason="stop",
                input_tokens=1,
                output_tokens=1,
            )
            span.write_result(
                {"content": result.content, "finish_reason": result.finish_reason}
            )
            span.write_operation_metas(
                {
                    "response_model": result.model,
                    "finish_reason": result.finish_reason,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            )
            return result
