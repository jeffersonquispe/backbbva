from __future__ import annotations

from celery import Celery

from src.infrastructure.core.config import genai_config


def create_celery_app(name: str = "lupita-worker") -> Celery:
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
    )
    app.autodiscover_tasks(["src.infrastructure.queue.celery"])
    return app


app = create_celery_app()
