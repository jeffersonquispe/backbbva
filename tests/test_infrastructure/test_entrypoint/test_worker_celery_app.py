import os

# The standalone Celery app imports the shared runtime configuration.
os.environ.setdefault("API_V0_STR", "/api/v0")
os.environ.setdefault("GENAI_ENVIRONMENT", "test")

from src.infrastructure.entrypoint.worker.celery.celery_app import app, periodic_schedule


def test_periodic_schedule_reconciles_async_operations() -> None:
    schedule = periodic_schedule(
        reconcile_interval_seconds=90,
        reconcile_limit=250,
        test_run_cleanup_interval_seconds=3600,
    )

    reconcile_rollups = schedule.pop("reconcile-alert-rollups")
    schedule.pop("record-operational-state")
    assert schedule == {
        "reconcile-async-operations": {
            "task": "async_operations.reconcile",
            "schedule": 90,
            "args": (250,),
        },
        "cleanup-test-runs": {
            "task": "test_runs.cleanup",
            "schedule": 3600,
        },
    }
    assert reconcile_rollups["task"] == "metrics.reconcile_alert_rollups"


def test_alert_rollup_reconciliation_runs_daily_at_2am_operations_time() -> None:
    entry = app.conf.beat_schedule["reconcile-alert-rollups"]
    schedule = entry["schedule"]

    assert entry["task"] == "metrics.reconcile_alert_rollups"
    assert schedule.hour == {2} and schedule.minute == {0}
    assert schedule.day_of_week == set(range(7))
    # crontab is evaluated in the app timezone (OPERATIONS_TIMEZONE).
    assert app.conf.timezone == "America/Bogota"


def test_worker_app_installs_periodic_schedule() -> None:
    entry = app.conf.beat_schedule["reconcile-async-operations"]

    assert entry["task"] == "async_operations.reconcile"
    assert entry["schedule"] == 60
    assert entry["args"] == (100,)
    assert app.conf.beat_schedule["cleanup-test-runs"]["schedule"] == 3600


def test_operational_state_is_sampled_every_minute() -> None:
    entry = app.conf.beat_schedule["record-operational-state"]

    assert entry["task"] == "metrics.record_operational_state"
    assert entry["schedule"] == 60
    # A tick not picked up within its interval is dropped, never queued up.
    assert entry["options"] == {"expires": 60}
