"""Event-simulator Celery worker entrypoint - separate broker/result DB and
queue from aria-worker (EVENT_SIMULATOR_CELERY_* config vars), so a runaway
simulation can never starve aria-worker's Celery pool."""
