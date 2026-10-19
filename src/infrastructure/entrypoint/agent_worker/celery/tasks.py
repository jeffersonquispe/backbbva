from __future__ import annotations

from src.infrastructure.agents.factories import get_agent_session_repository
from src.infrastructure.entrypoint.agent_worker.celery.celery_app import app
from src.infrastructure.queues.celery.agent_dispatcher import (
    enqueue_agent_session_tick,
)
from src.infrastructure.workflows.celery.task_factories import (
    get_agent_iteration_use_case,
    get_recover_stale_agent_runs_use_case,
)


@app.task(name="agent.orchestrate_session", acks_late=True)
def orchestrate_agent_session(session_id: str) -> dict[str, str]:
    status = get_agent_iteration_use_case().execute(session_id)
    session = get_agent_session_repository().get(session_id)
    if session is not None and session.status.value == "ACTIVE":
        enqueue_agent_session_tick(session_id, countdown=2)
    return {"status": status}


@app.task(name="agent.recover_stale_runs", acks_late=True)
def recover_stale_agent_runs(limit: int = 100) -> dict[str, int]:
    session_ids = get_recover_stale_agent_runs_use_case().execute(limit)
    for session_id in session_ids:
        enqueue_agent_session_tick(session_id)
    return {"recovered_sessions": len(session_ids)}
