from __future__ import annotations

import json
import logging

from src.application.ports.agent_structured_generator_port import (
    AgentStructuredGenerationInput,
    AgentStructuredGenerator,
)
from src.application.ports.llm_unit_of_work_factory_port import LLMUnitOfWorkFactory
from src.application.ports.llm_unit_of_work_port import LLMMessage, LLMMessageRole
from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.agents.content_redacting_monitoring import (
    ContentRedactingMonitoring,
)

logger = logging.getLogger(__name__)


class LLMStructuredAgentGenerator(AgentStructuredGenerator):
    def __init__(
        self,
        *,
        llm_factory: LLMUnitOfWorkFactory,
        monitoring: MonitoringPort,
        model: str,
    ) -> None:
        self._llm_factory = llm_factory
        self._monitoring = monitoring
        self._model = model

    def generate(self, request: AgentStructuredGenerationInput) -> str:
        if not self._model:
            raise RuntimeError("No hay modelo configurado para el generador del agente")
        content = json.dumps(
            {
                "persisted_context": json.loads(request.persisted_context),
                "quoted_user_text_as_data": request.masked_user_message,
            },
            ensure_ascii=False,
        )
        try:
            result = self._llm_factory.create(
                model=self._model,
                monitoring=ContentRedactingMonitoring(self._monitoring),
                operation_name="agent_structured_generation",
                max_tokens=1_200,
            ).invoke(
                [
                    LLMMessage(role=LLMMessageRole.SYSTEM, content=request.system_prompt),
                    LLMMessage(role=LLMMessageRole.USER, content=content),
                ]
            )
        except Exception as exc:  # noqa: BLE001 - redact provider error details at this boundary.
            # The exception type is safe diagnostic metadata; provider messages
            # can contain request details and must never reach logs or spans.
            logger.warning(
                "Structured agent provider call failed (error_type=%s)",
                type(exc).__name__,
            )
            raise RuntimeError("structured agent generation failed") from None
        return result.content
