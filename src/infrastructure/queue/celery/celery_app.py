from src.infrastructure.queues.celery.celery_app import app, create_celery_app

__all__ = ["app", "create_celery_app"]
