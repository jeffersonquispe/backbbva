from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CreateAgentSessionRequest(BaseModel):
    mode: Literal["assistant", "optimization"]
    scope: list[Literal["library", "configuration", "vector_store", "model"]] = Field(
        default_factory=list
    )
    requested_budget: dict[str, int] = Field(default_factory=dict)


class AgentSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    mode: str
    status: str
    created_at: datetime
    updated_at: datetime
    budget_limits: dict[str, int]
    prompt_versions: dict[str, dict[str, str]]
    rev: int


class AgentPackageSummaryResponse(BaseModel):
    package_id: str
    session_id: str
    iteration_number: int
    status: str
    content_hash: str | None
    created_at: datetime | None
    sealed_at: datetime | None


class SendAgentMessageRequest(BaseModel):
    client_message_id: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1)


class AgentMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: str
    client_message_id: str
    seq: int
    role: str
    content: str
    created_at: datetime
    redaction_counts: dict[str, int]
    extracted_insight_ids: tuple[str, ...] = ()


class AgentChatTurnResponse(BaseModel):
    user_message: AgentMessageResponse
    assistant_message: AgentMessageResponse | None
    proposed_insights: list[AgentInsightResponse] = Field(default_factory=list)


class AgentInsightResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    insight_id: str
    kind: str
    statement: str
    scope: dict[str, str]
    status: str
    proposed_by: str
    source_message_id: str | None
    created_at: datetime
    confidence: float | None


class AgentLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_type: str
    source_id: str
    relation: str
    target_type: str
    target_id: str
    created_at: datetime


class AgentSessionSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    version: int
    content: dict[str, object]
    covers_seq_from: int
    covers_seq_to: int
    created_at: datetime
