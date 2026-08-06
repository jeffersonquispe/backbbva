from __future__ import annotations

from src.infrastructure.queue.celery.celery_app import app


@app.task(name="queue.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
