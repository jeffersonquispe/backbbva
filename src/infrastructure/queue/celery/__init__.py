"""Celery queue adapter."""

from src.infrastructure.queue.celery.celery_app import app, create_celery_app

__all__ = ["app", "create_celery_app"]
