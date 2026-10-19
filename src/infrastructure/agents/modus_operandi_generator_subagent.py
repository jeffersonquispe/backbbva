from __future__ import annotations

import json
from typing import Any

from src.application.ports.agent_structured_generator_port import (
    AgentStructuredGenerationInput,
    AgentStructuredGenerator,
)
from src.application.ports.agent_subagent_port import (
    AgentSubagentInput,
    AgentSubagentOutput,
)


class ModusOperandiGeneratorSubagent:
    name = "modus_operandi_generator"

    def __init__(self, generator: AgentStructuredGenerator) -> None:
        self._generator = generator

    def execute(self, request: AgentSubagentInput) -> AgentSubagentOutput:
        system_prompt = request.scope.get("system_prompt")
        if not isinstance(system_prompt, str) or not system_prompt:
            return AgentSubagentOutput(
                subagent=self.name,
                error_code="PROMPT_UNAVAILABLE",
            )
        context = {
            "operation": request.scope.get("operation"),
            "current_entry": request.scope.get("current_entry"),
        }
        try:
            raw = self._generator.generate(
                AgentStructuredGenerationInput(
                    system_prompt=system_prompt,
                    persisted_context=json.dumps(context, ensure_ascii=False),
                    masked_user_message=request.hypothesis,
                )
            )
            payload: Any = json.loads(_strip_json_fence(raw))
        except (ValueError, TypeError):
            return AgentSubagentOutput(
                subagent=self.name,
                error_code="GENERATION_INVALID",
            )
        if not isinstance(payload, dict) or not isinstance(payload.get("draft"), dict):
            return AgentSubagentOutput(
                subagent=self.name,
                error_code="GENERATION_INVALID",
            )
        return AgentSubagentOutput(
            subagent=self.name,
            contribution=payload,
            verification_status="PENDING_VERIFICATION",
        )


def _strip_json_fence(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```") and value.endswith("```"):
        value = value[3:-3].strip()
        if value.startswith("json"):
            value = value[4:].strip()
    return value
