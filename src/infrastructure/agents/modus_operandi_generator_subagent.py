from __future__ import annotations

import json
from typing import Any

from src.application.ports.agent_chat_responder_port import (
    AgentChatInput,
    AgentChatResponder,
)
from src.application.ports.agent_subagent_port import (
    AgentSubagentInput,
    AgentSubagentOutput,
)


class ModusOperandiGeneratorSubagent:
    name = "modus_operandi_generator"

    def __init__(self, responder: AgentChatResponder) -> None:
        self._responder = responder

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
            response = self._responder.respond(
                AgentChatInput(
                    system_prompt=system_prompt,
                    persisted_context=json.dumps(context, ensure_ascii=False),
                    masked_user_message=request.hypothesis,
                )
            )
            payload: Any = json.loads(response.text)
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
