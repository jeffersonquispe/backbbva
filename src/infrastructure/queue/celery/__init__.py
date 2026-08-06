"""Celery queue adapter."""

from src.infrastructure.queues.celery import app, create_celery_app

__all__ = ["app", "create_celery_app"]

__all__ = ["app", "create_celery_app"]
