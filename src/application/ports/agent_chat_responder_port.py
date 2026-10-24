from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.application.ports.agent_project_tools_port import AgentProjectTools


@dataclass(frozen=True)
class AgentChatInput:
    system_prompt: str
    persisted_context: str
    masked_user_message: str
    tools: AgentProjectTools | None = None


@dataclass(frozen=True)
class AgentInsightProposal:
    kind: str
    statement: str
    scope: dict[str, str]
    confidence: float | None = None


@dataclass(frozen=True)
class AgentChatOutput:
    text: str
    proposals: tuple[AgentInsightProposal, ...] = ()
    # Project-graph node ids the model recommends opening; validated by the caller.
    references: tuple[str, ...] = ()


class AgentChatResponder(Protocol):
    def respond(self, request: AgentChatInput) -> AgentChatOutput: ...
