"""Worker entrypoint name for the Celery app (``celery -A ...:app``).

The app itself lives in ``queues/celery/app.py`` so dispatchers and routers
can send tasks without depending on the worker entrypoint (CA-004).
"""

from src.infrastructure.queues.celery.app import (
    OPERATIONAL_STATE_INTERVAL_SECONDS,
    app,
    create_celery_app,
    periodic_schedule,
)

__all__ = [
    "OPERATIONAL_STATE_INTERVAL_SECONDS",
    "app",
    "create_celery_app",
    "periodic_schedule",
]
