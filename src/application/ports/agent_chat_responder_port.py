from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AgentChatInput:
    system_prompt: str
    persisted_context: str
    masked_user_message: str


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


class AgentChatResponder(Protocol):
    def respond(self, request: AgentChatInput) -> AgentChatOutput: ...
