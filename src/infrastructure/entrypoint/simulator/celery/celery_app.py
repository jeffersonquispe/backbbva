from __future__ import annotations

import os

from celery import Celery

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.audit_celery import register_audit_signals

# Celery resolves conf.broker_url/result_backend by checking the
# CELERY_BROKER_URL/CELERY_RESULT_BACKEND environment variables on every
# access, ahead of whatever is passed to Celery(broker=..., backend=...) or
# set via conf.update() - a real quirk (verified against celery 5.6.2), not
# specific to this app. Harmless when this module runs standalone
# (simulator-worker's own container, which never sets those two generic
# names), but aria-api's process *does* set them for its own unrelated
# Celery producer (entrypoint/worker/celery/), and now also imports this
# module (infrastructure/queues/celery/simulation_dispatcher.py) to enqueue
# ticks - without this, every tick would silently land on aria-api's own
# broker/db instead of this app's EVENT_SIMULATOR_CELERY_* one. genai_config
# already captured the real values for aria-api's own Celery app by the time
# this module is ever imported, so deleting these two names from os.environ
# here is safe process-wide.
os.environ.pop("CELERY_BROKER_URL", None)
os.environ.pop("CELERY_RESULT_BACKEND", None)


def create_celery_app(name: str = "aria-event-simulator") -> Celery:
    register_audit_signals()
    app = Celery(
        name,
        broker=genai_config.EVENT_SIMULATOR_CELERY_BROKER_URL,
        backend=genai_config.EVENT_SIMULATOR_CELERY_RESULT_BACKEND,
    )
    app.conf.update(
        task_default_queue=genai_config.EVENT_SIMULATOR_CELERY_QUEUE,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        # Messages/ETAs stay UTC; crontab-style schedules (e.g. closing a
        # day of metric rollups at local midnight) run on Bogotá time.
        timezone=genai_config.OPERATIONS_TIMEZONE,
        enable_utc=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
    )
    app.autodiscover_tasks(["src.infrastructure.entrypoint.simulator.celery"])
    return app


app = create_celery_app()
