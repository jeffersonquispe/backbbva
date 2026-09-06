from __future__ import annotations

from src.application.dtos.alert_dtos import CurateAlertToDatasetInput
from src.application.dtos.dataset_dtos import AppendDatasetRowsOutput
from src.application.ports.alert_port import AlertRepository
from src.application.ports.dataset_analysis_dispatcher_port import (
    DatasetAnalysisDispatcher,
)
from src.application.ports.dataset_analysis_port import DatasetSummaryRepository
from src.application.ports.dataset_port import DatasetRepository
from src.application.use_cases.datasets.append_dataset_rows import (
    append_rows_and_dispatch,
)


class CurateAlertToDatasetUseCase:
    """The analyst-facing "Al dataset" action: adds one alert's payload as a
    row in an existing training dataset. AlertRecord.payload is already the
    same dotted-header-derived nested-dict shape DatasetRepository's
    get_rows()/append_rows() use (see csv_utils.py's unflatten_row/
    flatten_row) - so no field mapping is needed here. Both storage
    adapters' append_rows() already drops any flattened key the target
    dataset's header doesn't have (extrasaction="ignore"), which is what
    implements "map by field-name intersection" for a payload shaped
    differently than the dataset's columns - no special-casing needed here.
    """

    def __init__(
        self,
        alert_repository: AlertRepository,
        dataset_repository: DatasetRepository,
        summary_repository: DatasetSummaryRepository,
        dispatcher: DatasetAnalysisDispatcher,
    ) -> None:
        self._alerts = alert_repository
        self._datasets = dataset_repository
        self._summaries = summary_repository
        self._dispatcher = dispatcher

    def execute(self, input: CurateAlertToDatasetInput) -> AppendDatasetRowsOutput:
        alert = self._alerts.get(input.alert_id)
        if alert is None:
            raise LookupError(f"Alert '{input.alert_id}' not found")
        return append_rows_and_dispatch(
            dataset_repository=self._datasets,
            summary_repository=self._summaries,
            dispatcher=self._dispatcher,
            name=input.dataset_name,
            rows=[alert.payload],
        )
