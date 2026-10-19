from __future__ import annotations

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportResult,
    AnalystCapacityImportStatus,
)
from src.application.ports.analyst_capacity_import_status_reader_port import (
    AnalystCapacityImportStatusReader,
)
from src.application.use_cases.analyst_capacity.get_analyst_capacity_import import (
    GetAnalystCapacityImportUseCase,
)
from src.domain.configurations.entities import (
    DayProfile,
)


class InMemoryAnalystCapacityImportStatusReader(AnalystCapacityImportStatusReader):
    def __init__(self, result: AnalystCapacityImportResult) -> None:
        self._result = result
        self.read_task_ids: list[str] = []

    def read(self, task_id: str) -> AnalystCapacityImportResult:
        self.read_task_ids.append(task_id)
        return self._result


def test_get_returns_ready_result_from_reader() -> None:
    profile = DayProfile(
        id="imp-1", name="Día regular", description="", hourly=[4] * 24
    )
    reader = InMemoryAnalystCapacityImportStatusReader(
        AnalystCapacityImportResult(
            status=AnalystCapacityImportStatus.READY,
            profiles=[profile],
            day_overrides={15: "imp-1"},
        )
    )
    use_case = GetAnalystCapacityImportUseCase(reader=reader)

    result = use_case.execute("task-123")

    assert reader.read_task_ids == ["task-123"]
    assert result.status == AnalystCapacityImportStatus.READY
    assert result.profiles == [profile]
    assert result.day_overrides == {15: "imp-1"}


def test_get_passes_through_failed_result() -> None:
    reader = InMemoryAnalystCapacityImportStatusReader(
        AnalystCapacityImportResult(
            status=AnalystCapacityImportStatus.FAILED,
            error="Hoja 'Perfiles' no tiene perfiles.",
        )
    )
    use_case = GetAnalystCapacityImportUseCase(reader=reader)

    result = use_case.execute("task-456")

    assert result.status == AnalystCapacityImportStatus.FAILED
    assert result.error == "Hoja 'Perfiles' no tiene perfiles."
