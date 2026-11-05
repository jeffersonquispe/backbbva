from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from src.application.use_cases.agent.chat_with_agent import (
    AgentChatNotFoundError,
    AgentChatPolicyError,
    ChatWithAgentInput,
)
from src.infrastructure.agents.factories import (
    get_agent_iteration_repository,
    get_agent_run_repository,
    get_agent_session_repository,
)
from src.infrastructure.entrypoint.agent_worker.celery.celery_app import app
from src.infrastructure.queues.celery.agent_dispatcher import (
    enqueue_agent_session_tick,
)
from src.infrastructure.workflows.celery.task_factories import (
    get_agent_entity_claim_use_case,
    get_agent_iteration_use_case,
    get_chat_with_agent_use_case,
    get_global_pipeline_evaluation_use_case,
    get_recover_stale_agent_runs_use_case,
    get_worker_retrospective_validation_use_case,
)


@app.task(name="optimizer.evaluate_global_pipeline", acks_late=True)
def evaluate_global_pipeline(snapshot_id: str) -> dict[str, str]:
    result = get_global_pipeline_evaluation_use_case().execute(snapshot_id=snapshot_id)
    return {"status": result.status, "subject_id": result.subject_id}


# A candidate job renews its run lease while it works, so the recovery sweep
# only closes candidates whose worker really died.
RUN_LEASE_SECONDS = 90
RUN_HEARTBEAT_SECONDS = 30


@app.task(name="agent.orchestrate_session", acks_late=True)
def orchestrate_agent_session(session_id: str) -> dict[str, str]:
    get_agent_entity_claim_use_case().heartbeat(session_id)
    status = get_agent_iteration_use_case().execute(session_id)
    session = get_agent_session_repository().get(session_id)
    if session is not None and session.status.value == "ACTIVE":
        # While parallel candidates run there is nothing to plan: poll slower.
        countdown = 10 if status == "waiting_for_experiments" else 2
        enqueue_agent_session_tick(session_id, countdown=countdown)
    return {"status": status}


@app.task(name="agent.run_candidate", acks_late=True)
def run_agent_candidate(session_id: str, iteration_number: int) -> dict[str, str]:
    """Run one optimizer candidate planned by a tick, in parallel with its siblings."""
    stop = threading.Event()
    run_ids = _candidate_run_ids(session_id, iteration_number)

    def heartbeat() -> None:
        runs = get_agent_run_repository()
        while not stop.wait(RUN_HEARTBEAT_SECONDS):
            until = datetime.now(UTC) + timedelta(seconds=RUN_LEASE_SECONDS)
            for run_id in run_ids:
                runs.extend_lease(run_id, until)

    beat = threading.Thread(
        target=heartbeat, name="agent-candidate-heartbeat", daemon=True
    )
    beat.start()
    try:
        status = get_agent_iteration_use_case().run_candidate(
            session_id, iteration_number
        )
    finally:
        stop.set()
        beat.join(timeout=5)
    enqueue_agent_session_tick(session_id, countdown=1)
    return {"status": status}


def _candidate_run_ids(session_id: str, iteration_number: int) -> tuple[str, ...]:
    iteration = get_agent_iteration_repository().get(session_id, iteration_number)
    return iteration.run_ids if iteration is not None else ()


@app.task(name="agent.validate_retrospective", acks_late=True)
def validate_retrospective(validation_id: str) -> dict[str, str]:
    """Replay the pinned stacks through the real pipeline for a release check."""
    result = get_worker_retrospective_validation_use_case().complete(validation_id)
    return {"status": result.status.value if result is not None else "NOT_FOUND"}


@app.task(name="agent.recover_stale_runs", acks_late=True)
def recover_stale_agent_runs(limit: int = 100) -> dict[str, int]:
    session_ids = get_recover_stale_agent_runs_use_case().execute(limit)
    for session_id in session_ids:
        enqueue_agent_session_tick(session_id)
    return {"recovered_sessions": len(session_ids)}


CHAT_REPLY_MAX_RETRIES = 2
CHAT_REPLY_RETRY_SECONDS = 3


@app.task(name="agent.chat_reply", bind=True, acks_late=True)
def chat_reply(
    self,
    session_id: str,
    owner_id: str,
    client_message_id: str,
    page_path: str,
    role: str,
) -> dict[str, str]:
    """Write the assistant reply for a turn the API already stored.

    Safe to repeat: the reply is keyed by ``client_message_id``. After the last
    retry a safe error marker is stored so the polling client stops waiting.
    """
    request = ChatWithAgentInput(
        session_id=session_id,
        owner_id=owner_id,
        client_message_id=client_message_id,
        content="",
        page_path=page_path,
        role=role,
    )
    use_case = get_chat_with_agent_use_case()
    try:
        use_case.answer(request)
    except (AgentChatNotFoundError, AgentChatPolicyError):
        # Nothing a retry can fix (session gone, assistant switched off).
        try:
            use_case.fail(request, "CHAT_POLICY")
        except AgentChatNotFoundError:
            pass
        return {"status": "rejected"}
    except Exception as error:  # noqa: BLE001 - any provider error is retried
        if self.request.retries < CHAT_REPLY_MAX_RETRIES:
            raise self.retry(exc=error, countdown=CHAT_REPLY_RETRY_SECONDS)
        use_case.fail(request, "CHAT_UNAVAILABLE")
        return {"status": "failed"}
    return {"status": "answered"}
