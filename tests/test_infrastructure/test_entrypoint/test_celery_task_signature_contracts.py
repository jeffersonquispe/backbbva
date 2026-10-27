import inspect

from src.infrastructure.entrypoint.agent_worker.celery import tasks as agent_tasks
from src.infrastructure.entrypoint.simulator.celery import tasks as simulator_tasks
from src.infrastructure.entrypoint.worker.celery import tasks as worker_tasks

TASK_GROUPS = (
    (worker_tasks.app, worker_tasks.__name__),
    (agent_tasks.app, agent_tasks.__name__),
    (simulator_tasks.app, simulator_tasks.__name__),
)
EXPECTED_CELERY_TASK_COUNT = 33


def test_all_project_tasks_have_serializable_signature_annotations() -> None:
    project_tasks = [
        task
        for app, module_name in TASK_GROUPS
        for task in app.tasks.values()
        if task.__module__ == module_name
    ]

    assert len(project_tasks) == EXPECTED_CELERY_TASK_COUNT
    for task in project_tasks:
        signature = inspect.signature(task.run)
        assert signature.return_annotation is not inspect.Signature.empty, task.name
        assert all(
            parameter.annotation is not inspect.Signature.empty
            for parameter in signature.parameters.values()
        ), task.name


def test_all_project_task_apps_use_json_message_serialization() -> None:
    for app, _ in TASK_GROUPS:
        assert app.conf.task_serializer == "json"
        assert "json" in app.conf.accept_content
