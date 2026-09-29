from __future__ import annotations

from celery import Celery

from src.infrastructure.core.config import genai_config


def periodic_schedule(
    reconcile_interval_seconds: int,
    reconcile_limit: int,
    test_run_cleanup_interval_seconds: int,
) -> dict[str, dict]:
    """Return the global maintenance schedule owned by the single Beat pod.

    Scenario generation intentionally does not appear here: its tick is
    self-rescheduling so each running scenario keeps its own cadence.
    """
    return {
        "reconcile-async-operations": {
            "task": "async_operations.reconcile",
            "schedule": reconcile_interval_seconds,
            "args": (reconcile_limit,),
        },
        "cleanup-test-runs": {
            "task": "test_runs.cleanup",
            "schedule": test_run_cleanup_interval_seconds,
        },
    }


def create_celery_app(name: str = "aria-worker") -> Celery:
    app = Celery(
        name,
        broker=genai_config.CELERY_BROKER_URL,
        backend=genai_config.CELERY_RESULT_BACKEND,
    )
    app.conf.update(
        task_default_queue=genai_config.CELERY_DEFAULT_QUEUE,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        beat_schedule=periodic_schedule(
            genai_config.CELERY_RECONCILE_INTERVAL_SECONDS,
            genai_config.CELERY_RECONCILE_LIMIT,
            genai_config.CELERY_TEST_RUN_CLEANUP_INTERVAL_SECONDS,
        ),
    )
    app.autodiscover_tasks(["src.infrastructure.entrypoint.worker.celery"])
    return app


app = create_celery_app()
