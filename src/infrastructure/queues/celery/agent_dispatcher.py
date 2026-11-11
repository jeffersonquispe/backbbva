from __future__ import annotations

from src.application.ports.agent_candidate_dispatcher_port import (
    AgentCandidateDispatcher,
)
from src.application.ports.agent_chat_dispatcher_port import AgentChatDispatcher
from src.infrastructure.core.config import genai_config
from src.infrastructure.queues.celery.app import agent_app

AGENT_TICK_TASK = "agent.orchestrate_session"
AGENT_CANDIDATE_TASK = "agent.run_candidate"
AGENT_RETROSPECTIVE_TASK = "agent.validate_retrospective"
AGENT_CHAT_REPLY_TASK = "agent.chat_reply"


def enqueue_agent_session_tick(session_id: str, countdown: int = 0) -> None:
    agent_app.send_task(
        AGENT_TICK_TASK,
        args=[session_id],
        countdown=countdown,
        queue=agent_app.conf.task_default_queue,
    )


def enqueue_agent_candidate(session_id: str, iteration_number: int) -> None:
    agent_app.send_task(
        AGENT_CANDIDATE_TASK,
        args=[session_id, iteration_number],
        queue=agent_app.conf.task_default_queue,
    )


class CeleryAgentCandidateDispatcher(AgentCandidateDispatcher):
    """Each planned optimizer candidate becomes its own agent-queue task."""

    def dispatch(self, session_id: str, iteration_number: int) -> None:
        enqueue_agent_candidate(session_id, iteration_number)


def enqueue_retrospective_validation(validation_id: str) -> None:
    agent_app.send_task(
        AGENT_RETROSPECTIVE_TASK,
        args=[validation_id],
        queue=agent_app.conf.task_default_queue,
    )


class CeleryAgentChatDispatcher(AgentChatDispatcher):
    """Queues the assistant reply on the chat queue; the API never calls the LLM."""

    def dispatch(
        self,
        *,
        session_id: str,
        owner_id: str,
        client_message_id: str,
        page_path: str,
        role: str,
    ) -> None:
        agent_app.send_task(
            AGENT_CHAT_REPLY_TASK,
            args=[session_id, owner_id, client_message_id, page_path, role],
            queue=genai_config.CELERY_AGENT_CHAT_QUEUE,
        )
