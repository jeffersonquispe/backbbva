from __future__ import annotations


class DatasetAnalysisDispatcher:
    """Kicks off async analysis of an uploaded dataset - see
    infrastructure/queues/celery/dataset_analysis_dispatcher.py for the
    Celery adapter and infrastructure/entrypoint/worker/celery/tasks.py's
    analyze_dataset_task for what actually runs."""

    def dispatch(self, dataset_name: str) -> None:
        raise NotImplementedError
