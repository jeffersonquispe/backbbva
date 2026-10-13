from __future__ import annotations

import subprocess
import sys


def test_dispatcher_task_names_are_registered() -> None:
    import src.infrastructure.entrypoint.worker.celery.tasks  # noqa: F401
    from src.infrastructure.queues.celery import (
        alert_action_dispatcher,
        analyst_capacity_import_dispatcher,
        analyst_decision_documenter_dispatcher,
        analyst_escalation_dispatcher,
        dispatcher,
        fraud_label_review_import_dispatcher,
        model_training_dispatcher,
        reasoning_evaluation_dispatcher,
    )
    from src.infrastructure.queues.celery.app import app

    task_names = {
        dispatcher._TASK_NAME,
        alert_action_dispatcher._TASK_NAME,
        analyst_capacity_import_dispatcher._TASK_NAME,
        analyst_decision_documenter_dispatcher._TASK_NAME,
        analyst_escalation_dispatcher._TASK_NAME,
        "datasets.analyze",
        fraud_label_review_import_dispatcher._TASK_NAME,
        model_training_dispatcher._TASK_NAME,
        reasoning_evaluation_dispatcher._TASK_NAME,
    }
    assert task_names <= set(app.tasks)


def test_simulation_dispatcher_task_is_registered_on_simulator_app() -> None:
    from src.infrastructure.entrypoint.simulator.celery import tasks as simulator_tasks
    from src.infrastructure.entrypoint.simulator.celery.celery_app import app
    from src.infrastructure.queues.celery.simulation_dispatcher import (
        CelerySimulationDispatcher,
    )

    assert simulator_tasks.tick.name in app.tasks
    assert hasattr(CelerySimulationDispatcher, "dispatch")


def test_importing_api_routers_does_not_import_worker_entrypoint() -> None:
    script = """
import importlib
import pkgutil
import sys
import src.infrastructure.entrypoint.api.routers as routers
for module in pkgutil.iter_modules(routers.__path__, routers.__name__ + '.'):
    importlib.import_module(module.name)
assert not any(name.startswith('src.infrastructure.entrypoint.worker') for name in sys.modules)
"""
    subprocess.run([sys.executable, "-c", script], check=True)
