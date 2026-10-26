from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

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
    get_global_pipeline_evaluation_use_case,
    get_recover_stale_agent_runs_use_case,
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


@app.task(name="agent.recover_stale_runs", acks_late=True)
def recover_stale_agent_runs(limit: int = 100) -> dict[str, int]:
    session_ids = get_recover_stale_agent_runs_use_case().execute(limit)
    for session_id in session_ids:
        enqueue_agent_session_tick(session_id)
    return {"recovered_sessions": len(session_ids)}
