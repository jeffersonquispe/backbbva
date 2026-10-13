from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.application.ports.test_run_port import (
    TestRunConfig,
    TestRunRecord,
    TestRunStatus,
)
from src.domain.configurations.entities import (
    ConfigurationRef,
)
from src.infrastructure.persistence.database.dynamodb.repositories.test_run_repository import (
    _from_item,
    _to_item,
)


def _run(config: TestRunConfig) -> TestRunRecord:
    now = datetime.now(UTC)
    return TestRunRecord(
        id=uuid.uuid4(),
        name="run",
        dataset_name="ds",
        config=config,
        status=TestRunStatus.RUNNING,
        total=3,
        created_at=now,
        updated_at=now,
    )


def test_configuration_ref_round_trips_through_the_dynamodb_item() -> None:
    run = _run(TestRunConfig(configuration_ref=ConfigurationRef("cfg-1", 2)))

    assert _from_item(_to_item(run)).config.configuration_ref == ConfigurationRef(
        "cfg-1", 2
    )


def test_no_configuration_ref_round_trips_as_none() -> None:
    run = _run(TestRunConfig())

    assert _from_item(_to_item(run)).config.configuration_ref is None


def test_items_predating_configuration_ref_default_to_none() -> None:
    run = _run(TestRunConfig())
    item = _to_item(run)
    del item["configuration_ref"]

    assert _from_item(item).config.configuration_ref is None
