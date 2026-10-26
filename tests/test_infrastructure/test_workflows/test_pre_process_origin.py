from src.domain.alerts.entities import AlertOrigin
from src.infrastructure.workflows.celery.review_intake_steps import (
    _skip_external_enrichment,
)


def test_external_enrichment_is_reserved_for_production_alerts() -> None:
    assert not _skip_external_enrichment(AlertOrigin.PRODUCTION.value)
    assert not _skip_external_enrichment(AlertOrigin.MANUAL.value)
    assert _skip_external_enrichment(AlertOrigin.TEST_RUN.value)
    assert _skip_external_enrichment(AlertOrigin.SIMULATOR.value)
    assert _skip_external_enrichment(AlertOrigin.OPTIMIZER_EVALUATION.value)
