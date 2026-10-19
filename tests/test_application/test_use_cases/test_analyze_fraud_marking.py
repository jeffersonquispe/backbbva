from __future__ import annotations

from dataclasses import replace

from src.application.dtos.dataset_dtos import FraudMarkingAnalysisInput
from src.application.ports.async_operation_port import AsyncOperationStatus
from src.application.ports.dataset_port import DatasetRecord
from src.application.use_cases.datasets.analyze_fraud_marking import (
    AnalyzeFraudMarkingUseCase,
)


class InMemoryDatasetRepository:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list(self) -> list[DatasetRecord]:
        return [DatasetRecord(name="ds", row_count=len(self._rows))]

    def get_rows(self, name: str) -> list[dict]:
        return self._rows

    def delete(self, name: str) -> None:
        pass


class InMemoryAsyncOperationRepository:
    def __init__(self) -> None:
        self.operations = {}

    def create(self, operation):
        self.operations[operation.id] = operation
        return operation

    def get(self, operation_id):
        return self.operations.get(operation_id)

    def list(self, status=None, limit=100):
        return list(self.operations.values())[:limit]

    def list_active(self, limit=100):
        return []

    def update(self, operation_id, **changes):
        operation = self.operations.get(operation_id)
        if operation is None:
            return None
        updated = replace(operation, **changes)
        self.operations[operation_id] = updated
        return updated

    def delete(self, operation_id):
        self.operations.pop(operation_id, None)


def _input(**overrides) -> FraudMarkingAnalysisInput:
    defaults = dict(
        dataset_name="ds",
        first_mark_field="razon_marcacion",
        second_mark_field="marcacion_final",
        first_mark_time_field="fecha_primer_marcacion",
        second_mark_time_field="fecha_ultima_marcacion",
        positive_values=["risk"],
    )
    defaults.update(overrides)
    return FraudMarkingAnalysisInput(**defaults)


def test_schedule_creates_a_durable_async_operation() -> None:
    operations = InMemoryAsyncOperationRepository()
    use_case = AnalyzeFraudMarkingUseCase(
        InMemoryDatasetRepository([]), async_operation_repository=operations
    )

    operation_id = use_case.schedule(_input(positive_values=["risk", "risk-suspected"]))

    assert operation_id is not None
    operation = operations.get(operation_id)
    assert operation is not None
    assert operation.operation_type == "dataset.fraud_marking_analyze"
    assert operation.status == AsyncOperationStatus.PENDING
    assert operation.payload["positive_values"] == ["risk", "risk-suspected"]


def test_classifies_false_positives_false_negatives_and_properly_marked() -> None:
    rows = [
        # false positive: flagged first, cleared on review.
        {
            "razon_marcacion": "risk",
            "marcacion_final": "no-risk",
            "fecha_primer_marcacion": "2026-05-02 10:00:00",
            "fecha_ultima_marcacion": "2026-05-02 12:00:00",
        },
        # false negative: missed first, confirmed fraud on review.
        {
            "razon_marcacion": "no-risk",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "2026-05-02 10:00:00",
            "fecha_ultima_marcacion": "2026-05-03 10:00:00",
        },
        # properly marked, both positive.
        {
            "razon_marcacion": "risk",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-02 04:00:00",
        },
        # properly marked, both negative.
        {
            "razon_marcacion": "no-risk",
            "marcacion_final": "no-risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-02 00:00:00",
        },
        # skipped: missing second mark field entirely.
        {
            "razon_marcacion": "risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
        },
    ]
    use_case = AnalyzeFraudMarkingUseCase(InMemoryDatasetRepository(rows))

    output = use_case.execute(_input())

    assert output.evaluated_rows == 4
    assert output.skipped_rows == 1
    assert output.false_positives == 1
    assert output.false_negatives == 1
    assert output.properly_marked == 2


def test_multiple_positive_values_does_not_flag_a_move_between_them() -> None:
    rows = [
        # escalation within the positive class - risk-suspected -> risk is
        # not a remark, so this must land in properly_marked, not
        # false_positives or false_negatives.
        {
            "razon_marcacion": "risk-suspected",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-02 01:00:00",
        },
        # still a genuine false positive: positive first mark, negative
        # second mark, regardless of how many positive labels exist.
        {
            "razon_marcacion": "risk-suspected",
            "marcacion_final": "no-risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-02 01:00:00",
        },
    ]
    use_case = AnalyzeFraudMarkingUseCase(InMemoryDatasetRepository(rows))

    output = use_case.execute(_input(positive_values=["risk", "risk-suspected"]))

    assert output.evaluated_rows == 2
    assert output.properly_marked == 1
    assert output.false_positives == 1
    assert output.false_negatives == 0


def test_maturation_profile_computes_avg_min_max_p95_in_days() -> None:
    rows = [
        {
            "razon_marcacion": "risk",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-02 01:00:00",  # 1h
        },
        {
            "razon_marcacion": "risk",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-02 03:00:00",  # 3h
        },
        {
            "razon_marcacion": "risk",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-03 00:00:00",  # 24h
        },
    ]
    use_case = AnalyzeFraudMarkingUseCase(InMemoryDatasetRepository(rows))

    output = use_case.execute(_input())

    maturation = output.maturation
    assert maturation.sample_size == 3
    assert maturation.min_days == round(1 / 24, 2)
    assert maturation.max_days == 1.0
    assert maturation.avg_days == round((1 + 3 + 24) / 3 / 24, 2)
    assert maturation.p50_days == round(3 / 24, 2)
    assert maturation.p75_days == round(13.5 / 24, 2)
    assert maturation.p90_days == round(19.8 / 24, 2)
    # linear-interpolation percentile: rank = 0.95 * (3 - 1) = 1.9 -> between
    # sorted[1]=3 and sorted[2]=24, 0.9 of the way across.
    assert maturation.p95_days == round((3 + (24 - 3) * 0.9) / 24, 2)
    assert maturation.p98_days == round((3 + (24 - 3) * 0.96) / 24, 2)
    assert maturation.p99_days == round((3 + (24 - 3) * 0.98) / 24, 2)


def test_rows_with_unparseable_or_missing_timestamps_are_excluded_from_maturation() -> (
    None
):
    rows = [
        {
            "razon_marcacion": "risk",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "not-a-date",
            "fecha_ultima_marcacion": "2026-05-02 01:00:00",
        },
        {
            "razon_marcacion": "risk",
            "marcacion_final": "risk",
            "fecha_primer_marcacion": "2026-05-02 00:00:00",
            "fecha_ultima_marcacion": "2026-05-02 01:00:00",
        },
    ]
    use_case = AnalyzeFraudMarkingUseCase(InMemoryDatasetRepository(rows))

    output = use_case.execute(_input())

    assert output.evaluated_rows == 2
    assert output.maturation.sample_size == 1
    assert output.maturation.avg_days == round(1 / 24, 2)
