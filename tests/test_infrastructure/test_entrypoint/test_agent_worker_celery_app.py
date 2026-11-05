from src.infrastructure.entrypoint.agent_worker.celery import tasks
from src.infrastructure.queues.celery.app import agent_app, app


def test_agent_worker_uses_dedicated_queue_and_recovery_schedule() -> None:
    assert agent_app.conf.task_default_queue == "agent"
    assert app.conf.task_default_queue != agent_app.conf.task_default_queue
    assert agent_app.conf.beat_schedule["agent-recover-stale-runs"]["task"] == (
        "agent.recover_stale_runs"
    )


def test_agent_tasks_are_registered_on_the_dedicated_app() -> None:
    assert "agent.orchestrate_session" in tasks.app.tasks
    assert "agent.recover_stale_runs" in tasks.app.tasks


def test_chat_replies_use_their_own_queue_and_task() -> None:
    from src.infrastructure.queues.celery.agent_dispatcher import AGENT_CHAT_REPLY_TASK

    assert AGENT_CHAT_REPLY_TASK in tasks.app.tasks
    assert tasks.app.tasks[AGENT_CHAT_REPLY_TASK].acks_late is True
