from __future__ import annotations

from functools import lru_cache

from src.application.ports.analyst_capacity_import_port import (
    AnalystCapacityImportDispatcher,
)
from src.application.ports.analyst_capacity_import_status_reader_port import (
    AnalystCapacityImportStatusReader,
)
from src.application.use_cases.analyst_capacity.get_analyst_capacity_import import (
    GetAnalystCapacityImportUseCase,
)
from src.application.use_cases.analyst_capacity.upload_analyst_capacity_import import (
    UploadAnalystCapacityImportUseCase,
)


@lru_cache
def get_analyst_capacity_import_dispatcher() -> AnalystCapacityImportDispatcher:
    # Lazy import - keeps celery out of the API process's import graph.
    from src.infrastructure.queues.celery.analyst_capacity_import_dispatcher import (
        CeleryAnalystCapacityImportDispatcher,
    )

    return CeleryAnalystCapacityImportDispatcher()


@lru_cache
def get_analyst_capacity_import_status_reader() -> AnalystCapacityImportStatusReader:
    from src.infrastructure.queues.celery.analyst_capacity_import_status_reader import (
        CeleryAnalystCapacityImportStatusReader,
    )

    return CeleryAnalystCapacityImportStatusReader()


def get_upload_analyst_capacity_import_use_case() -> UploadAnalystCapacityImportUseCase:
    return UploadAnalystCapacityImportUseCase(
        dispatcher=get_analyst_capacity_import_dispatcher()
    )


def get_get_analyst_capacity_import_use_case() -> GetAnalystCapacityImportUseCase:
    return GetAnalystCapacityImportUseCase(
        reader=get_analyst_capacity_import_status_reader()
    )
