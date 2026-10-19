from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from src.application.ports.agent_chat_responder_port import (
    AgentChatInput,
    AgentChatOutput,
    AgentChatResponder,
    AgentInsightProposal,
)
from src.application.ports.agent_insight_port import (
    AgentInsight,
    AgentInsightKind,
    AgentInsightRepository,
    AgentInsightStatus,
)
from src.application.ports.agent_link_port import AgentLink, AgentLinkRepository
from src.application.ports.agent_message_port import (
    AgentMessage,
    AgentMessageRepository,
)
from src.application.ports.agent_prompt_port import AgentPromptRepository
from src.application.ports.agent_session_port import (
    AgentSessionRepository,
    AgentSessionStatus,
)
from src.application.ports.agent_session_summary_port import (
    AgentSessionSummary,
    AgentSessionSummaryRepository,
)
from src.application.ports.assistant_optimizer_settings_port import (
    AssistantOptimizerSettingsPort,
)
from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.personal_data_masker_port import PersonalDataMasker

CHAT_PROMPT = "agent.chat.system"
RECENT_CONTEXT_MESSAGES = 8
SUMMARY_MAX_CHARS = 4_000
MAX_INSIGHT_PROPOSALS = 5
CHAT_STATUSES = {
    AgentSessionStatus.DRAFT,
    AgentSessionStatus.ACTIVE,
    AgentSessionStatus.PAUSED,
    AgentSessionStatus.WAITING_USER,
    AgentSessionStatus.WAITING_APPROVAL,
}


class AgentChatNotFoundError(Exception):
    pass


class AgentChatPolicyError(Exception):
    pass


class AgentMessageTooLongError(Exception):
    pass


class AgentMessageLimitError(Exception):
    pass


@dataclass(frozen=True)
class ChatWithAgentInput:
    session_id: str
    owner_id: str
    client_message_id: str
    content: str


@dataclass(frozen=True)
class AgentChatTurn:
    user_message: AgentMessage
    assistant_message: AgentMessage | None
    proposed_insights: tuple[AgentInsight, ...] = ()


class ChatWithAgentUseCase:
    """Persist and answer one idempotent, irreversibly masked chat turn."""

    def __init__(
        self,
        *,
        sessions: AgentSessionRepository,
        messages: AgentMessageRepository,
        insights: AgentInsightRepository,
        links: AgentLinkRepository,
        summaries: AgentSessionSummaryRepository,
        prompts: AgentPromptRepository,
        settings: AssistantOptimizerSettingsPort,
        masker: PersonalDataMasker,
        responder: AgentChatResponder,
        clock: Clock,
        id_generator: IdGenerator,
    ) -> None:
        self._sessions = sessions
        self._messages = messages
        self._insights = insights
        self._links = links
        self._summaries = summaries
        self._prompts = prompts
        self._settings = settings
        self._masker = masker
        self._responder = responder
        self._clock = clock
        self._ids = id_generator

    def execute(self, request: ChatWithAgentInput) -> AgentChatTurn:
        session = self._sessions.get(request.session_id)
        if session is None or session.owner_id != request.owner_id:
            raise AgentChatNotFoundError("session not found")
        if session.status not in CHAT_STATUSES:
            raise AgentChatPolicyError("session cannot receive messages")
        settings = self._settings.get()
        if session.mode == "assistant" and not settings.assistant_enabled:
            raise AgentChatPolicyError("assistant is disabled")
        if len(request.content) > settings.assistant_max_message_chars:
            raise AgentMessageTooLongError("message exceeds configured character limit")
        if not request.client_message_id or len(request.client_message_id) > 128:
            raise AgentChatPolicyError("invalid client_message_id")
        try:
            UUID(request.client_message_id)
        except ValueError as error:
            raise AgentChatPolicyError(
                "client_message_id must be an opaque UUID"
            ) from error

        user_message = self._messages.get_by_client_message_id(
            request.session_id, request.client_message_id
        )
        assistant_key = f"{request.client_message_id}:assistant"
        if user_message is not None:
            assistant_message = self._messages.get_by_client_message_id(
                request.session_id, assistant_key
            )
            if assistant_message is not None:
                proposals = tuple(
                    insight
                    for insight_id in assistant_message.extracted_insight_ids
                    if (insight := self._insights.get(request.session_id, insight_id))
                    is not None
                )
                latest_summary = self._summaries.get_latest(request.session_id)
                if (
                    latest_summary is None
                    or latest_summary.covers_seq_to < assistant_message.seq
                ):
                    self._append_summary(
                        request.session_id,
                        user_message,
                        assistant_message,
                        list(proposals),
                    )
                return AgentChatTurn(user_message, assistant_message, proposals)
            masked_input = self._masker.mask(user_message.content)
        else:
            masked_input = self._masker.mask(request.content)

        if user_message is None:
            if (
                self._messages.count_for_session(request.session_id) + 2
                > settings.assistant_max_messages_per_session
            ):
                raise AgentMessageLimitError("session message limit reached")
            user_message = self._save_message(
                session_id=request.session_id,
                client_message_id=request.client_message_id,
                role="user",
                content=masked_input.text,
                author_id=request.owner_id,
                redaction_counts=masked_input.counts,
            )
        active_prompt = session.prompt_versions.get(CHAT_PROMPT)
        prompt = None
        if active_prompt:
            prompt = self._prompts.get_version(
                CHAT_PROMPT, int(active_prompt["version"])
            )
        if prompt is None:
            raise AgentChatPolicyError("session chat prompt is unavailable")

        summary = self._summaries.get_latest(request.session_id)
        floor = summary.covers_seq_to if summary else 0
        recent = self._messages.list_after_seq(request.session_id, floor, limit=50)
        recent = recent[-RECENT_CONTEXT_MESSAGES:]
        active_insights = self._insights.list_for_session(
            request.session_id, status=AgentInsightStatus.ACTIVE, limit=50
        )
        context = {
            "session": {
                "mode": session.mode,
                "status": session.status.value,
                "scope": session.scope,
            },
            "summary": summary.content if summary else {},
            "active_insights": [
                {
                    "kind": insight.kind.value,
                    "statement": insight.statement,
                    "scope": insight.scope,
                }
                for insight in active_insights
            ],
            "recent_messages": [
                {"role": message.role, "content": message.content} for message in recent
            ],
        }
        response = self._responder.respond(
            AgentChatInput(
                system_prompt=prompt.content,
                persisted_context=json.dumps(context, ensure_ascii=False),
                masked_user_message=masked_input.text,
            )
        )
        if not response.proposals:
            response = AgentChatOutput(
                text=response.text,
                proposals=_rule_based_proposal(masked_input.text),
            )
        masked_response = self._masker.mask(response.text)
        proposed = self._persist_proposals(
            request=request,
            user_message=user_message,
            proposals=response,
        )
        assistant_message = self._save_message(
            session_id=request.session_id,
            client_message_id=assistant_key,
            role="agent",
            content=masked_response.text[: settings.assistant_max_message_chars],
            author_id="aria",
            redaction_counts=masked_response.counts,
            extracted_insight_ids=tuple(item.insight_id for item in proposed),
        )
        self._append_summary(
            request.session_id, user_message, assistant_message, proposed
        )
        return AgentChatTurn(user_message, assistant_message, tuple(proposed))

    def _save_message(
        self,
        *,
        session_id: str,
        client_message_id: str,
        role: str,
        content: str,
        author_id: str,
        redaction_counts: dict[str, int],
        extracted_insight_ids: tuple[str, ...] = (),
    ) -> AgentMessage:
        session = self._sessions.get(session_id)
        if session is None:
            raise AgentChatNotFoundError("session not found")
        updated = self._sessions.increment_message_seq(session_id)
        return self._messages.create_once(
            AgentMessage(
                session_id=session_id,
                client_message_id=client_message_id,
                message_id=str(self._ids.new_id()),
                seq=updated,
                role=role,
                content=content,
                author_id=author_id,
                created_at=self._clock.now(),
                redaction_counts=redaction_counts,
                extracted_insight_ids=extracted_insight_ids,
                expires_at=self._clock.now()
                + timedelta(days=self._settings.get().chat_retention_days),
            )
        )

    def _persist_proposals(
        self,
        *,
        request: ChatWithAgentInput,
        user_message: AgentMessage,
        proposals: AgentChatOutput,
    ) -> list[AgentInsight]:
        now = self._clock.now()
        persisted: list[AgentInsight] = []
        for index, proposal in enumerate(proposals.proposals[:MAX_INSIGHT_PROPOSALS]):
            try:
                kind = AgentInsightKind(proposal.kind)
            except ValueError:
                continue
            masked = self._masker.mask(proposal.statement)
            safe_scope = {
                key: self._masker.mask(value).text[:200]
                for key, value in proposal.scope.items()
                if key in {"type", "ref"} and isinstance(value, str)
            }
            insight = AgentInsight(
                session_id=request.session_id,
                insight_id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"aria:{request.session_id}:{user_message.message_id}:{index}",
                    )
                ),
                kind=kind,
                statement=masked.text[:2_000],
                scope=safe_scope,
                status=AgentInsightStatus.PROPOSED,
                proposed_by="agent",
                author_id="aria",
                source_message_id=user_message.message_id,
                created_at=now,
                updated_at=now,
                confidence=(
                    min(1.0, max(0.0, proposal.confidence))
                    if proposal.confidence is not None
                    else None
                ),
                expires_at=now
                + timedelta(days=self._settings.get().chat_retention_days),
            )
            persisted.append(self._insights.create(insight))
            self._links.create_once(
                AgentLink(
                    session_id=request.session_id,
                    source_type="message",
                    source_id=user_message.message_id,
                    relation="proposes",
                    target_type="insight",
                    target_id=insight.insight_id,
                    created_at=now,
                    expires_at=now
                    + timedelta(days=self._settings.get().chat_retention_days),
                )
            )
        return persisted

    def _append_summary(
        self,
        session_id: str,
        user_message: AgentMessage,
        assistant_message: AgentMessage,
        proposals: list[AgentInsight],
    ) -> None:
        previous = self._summaries.get_latest(session_id)
        previous_content = previous.content if previous else {}
        prior_text = str(previous_content.get("text", ""))
        additions = [
            f"Usuario: {user_message.content}",
            f"ARIA: {assistant_message.content}",
        ]
        if proposals:
            additions.append(
                "Insights por confirmar: "
                + "; ".join(item.statement for item in proposals)
            )
        text = (prior_text + "\n" + "\n".join(additions)).strip()[-SUMMARY_MAX_CHARS:]
        decisions = _summary_items(previous_content.get("decisions"))
        learnings = _summary_items(previous_content.get("learnings"))
        open_questions = _summary_items(previous_content.get("open_questions"))
        for insight in proposals:
            statement = self._masker.mask(insight.statement).text[:500]
            if insight.kind == AgentInsightKind.DECISION:
                decisions.append(statement)
            elif insight.kind == AgentInsightKind.QUESTION:
                open_questions.append(statement)
            else:
                learnings.append(statement)
        next_version = (previous.version + 1) if previous else 1
        self._summaries.create(
            AgentSessionSummary(
                session_id=session_id,
                version=next_version,
                content={
                    "text": self._masker.mask(text).text,
                    "decisions": decisions[-20:],
                    "learnings": learnings[-20:],
                    "open_questions": open_questions[-20:],
                },
                covers_seq_from=(
                    previous.covers_seq_from if previous else user_message.seq
                ),
                covers_seq_to=assistant_message.seq,
                created_at=self._clock.now(),
                expires_at=self._clock.now()
                + timedelta(days=self._settings.get().chat_retention_days),
            )
        )


def _rule_based_proposal(text: str) -> tuple[AgentInsightProposal, ...]:
    normalized = text.casefold()
    if "prefiero" in normalized or "preferimos" in normalized:
        kind = AgentInsightKind.PREFERENCE
    elif "no debe" in normalized or "debe evitar" in normalized:
        kind = AgentInsightKind.CONSTRAINT
    elif "observo" in normalized or "reporto" in normalized:
        kind = AgentInsightKind.OBSERVATION
    else:
        return ()
    return (
        AgentInsightProposal(
            kind=kind.value,
            statement=text[:2_000],
            scope={"type": "all", "ref": "all"},
            confidence=0.5,
        ),
    )


def _summary_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
