"""Agent worker entrypoint: ``celery -A ...:app``."""

from src.infrastructure.queues.celery.app import agent_app as app

__all__ = ["app"]
