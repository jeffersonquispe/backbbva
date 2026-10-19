from __future__ import annotations

from src.infrastructure.queues.celery.app import agent_app

AGENT_TICK_TASK = "agent.orchestrate_session"


def enqueue_agent_session_tick(session_id: str, countdown: int = 0) -> None:
    agent_app.send_task(
        AGENT_TICK_TASK,
        args=[session_id],
        countdown=countdown,
        queue=agent_app.conf.task_default_queue,
    )
