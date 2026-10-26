from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.audit_celery import register_audit_signals

OPERATIONAL_STATE_INTERVAL_SECONDS = 60


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
        # LocalStack and DynamoDB Local retain TTL-expired rows forever.
        "cleanup-expired-metric-rollups": {
            "task": "metrics.cleanup_expired_rollups",
            "schedule": crontab(hour=4, minute=0),
        },
        # Keep the hot audit table bounded while preserving history in MinIO.
        "archive-audit-log": {
            "task": "audit.archive_log",
            "schedule": 60.0,
            "options": {"expires": 60},
        },
        # R7 safety net: 02:00 in the app's Celery timezone
        # (OPERATIONS_TIMEZONE, Bogota) - quiet hours, after the day closed.
        "reconcile-alert-rollups": {
            "task": "metrics.reconcile_alert_rollups",
            "schedule": crontab(hour=2, minute=0),
        },
        # Object-storage retention sweep: 03:00 Bogota, after the nightly
        # rollup reconciliation. No-op unless OBJECT_STORAGE_RETENTION_ENABLED.
        "object-storage-retention": {
            "task": "object_storage.retention",
            "schedule": crontab(hour=3, minute=0),
        },
        "analyze-alert-schema-presence": {
            "task": "alert_schema.analyze_presence",
            "schedule": crontab(hour=2, minute=30),
        },
        # T3/T5 operational gauges (agent on/off, operating hours, analyst
        # queue, capacity) - also the "dead man's switch" heartbeat. A stale
        # sample is useless, so a tick not picked up within its own
        # interval expires instead of piling up behind a busy worker.
        "record-operational-state": {
            "task": "metrics.record_operational_state",
            "schedule": OPERATIONAL_STATE_INTERVAL_SECONDS,
            "options": {"expires": OPERATIONAL_STATE_INTERVAL_SECONDS},
        },
        # H6: evaluate configured sampler intervals in Bogotá time. The task
        # uses persisted state to enforce weekly defaults, cooldown, and retry
        # idempotency before materializing a snapshot.
        "sample-mature-datasets": {
            "task": "datasets.sample_mature",
            "schedule": crontab(hour=4, minute=15),
            "options": {"expires": 24 * 60 * 60},
        },
    }


def create_celery_app(name: str = "aria-worker") -> Celery:
    register_audit_signals()
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
        # Messages/ETAs stay UTC; crontab-style schedules (e.g. closing a
        # day of metric rollups at local midnight) run on Bogotá time.
        timezone=genai_config.OPERATIONS_TIMEZONE,
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


def create_agent_celery_app(name: str = "aria-agent-worker") -> Celery:
    """Build the isolated Celery app used only by the assistant agent."""
    register_audit_signals()
    agent_app = Celery(
        name,
        broker=genai_config.CELERY_BROKER_URL,
        backend=genai_config.CELERY_RESULT_BACKEND,
    )
    agent_app.conf.update(
        task_default_queue=genai_config.CELERY_AGENT_QUEUE,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone=genai_config.OPERATIONS_TIMEZONE,
        enable_utc=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        beat_schedule={
            "agent-recover-stale-runs": {
                "task": "agent.recover_stale_runs",
                "schedule": 30.0,
            }
        },
    )
    agent_app.autodiscover_tasks(["src.infrastructure.entrypoint.agent_worker.celery"])
    return agent_app


app = create_celery_app()
agent_app = create_agent_celery_app()
