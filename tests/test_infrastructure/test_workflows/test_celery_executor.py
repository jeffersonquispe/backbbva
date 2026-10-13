import os

os.environ.setdefault("API_V0_STR", "/api/v0")
os.environ.setdefault("GENAI_ENVIRONMENT", "test")

from src.domain.alerts.entities import (
    AlertOrigin,
)
from src.infrastructure.workflows.celery.executor import queue_for_origin


def test_test_run_workflows_use_the_dedicated_queue() -> None:
    assert queue_for_origin(AlertOrigin.TEST_RUN.value) == "test"


def test_non_test_workflows_stay_on_the_default_queue() -> None:
    assert queue_for_origin(AlertOrigin.PRODUCTION.value) == "default"
    assert queue_for_origin(None) == "default"
