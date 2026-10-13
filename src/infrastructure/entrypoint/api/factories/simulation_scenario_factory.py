from __future__ import annotations

import random
from functools import lru_cache

from src.application.dtos.dataset_dtos import GetDatasetRowsInput
from src.application.ports.dataset_reader_gateway_port import DatasetReaderGateway
from src.application.ports.simulation_dispatcher_port import SimulationDispatcher
from src.application.ports.simulation_scenario_port import SimulationScenarioRepository
from src.application.use_cases.datasets.get_dataset_rows import GetDatasetRowsUseCase
from src.application.use_cases.event_simulation.create_simulation_scenario import (
    CreateSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.delete_simulation_scenario import (
    DeleteSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.generate_event_batch import (
    GenerateEventBatchUseCase,
)
from src.application.use_cases.event_simulation.get_simulation_scenario import (
    GetSimulationScenarioUseCase,
)
from src.application.use_cases.event_simulation.get_simulation_status import (
    GetSimulationStatusUseCase,
)
from src.application.use_cases.event_simulation.list_simulation_scenarios import (
    ListSimulationScenariosUseCase,
)
from src.application.use_cases.event_simulation.pause_simulation import (
    PauseSimulationUseCase,
)
from src.application.use_cases.event_simulation.seed_simulation_from_dataset import (
    SeedSimulationFromDatasetUseCase,
)
from src.application.use_cases.event_simulation.start_simulation import (
    StartSimulationUseCase,
)
from src.application.use_cases.event_simulation.stop_simulation import (
    StopSimulationUseCase,
)
from src.application.use_cases.event_simulation.update_simulation_scenario import (
    UpdateSimulationScenarioUseCase,
)
from src.infrastructure.entrypoint.api.factories.alert_schema_factory import (
    get_alert_schema_repository,
)
from src.infrastructure.entrypoint.api.factories.dataset_factory import (
    get_dataset_repository,
    get_dataset_summary_repository,
)
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.simulation_scenario_repository import (
    DynamoSimulationScenarioRepository,
)

_DATASET_SAMPLE_WINDOW = 500


class LocalDatasetReaderGateway(DatasetReaderGateway):
    """In-process equivalent of the simulator-worker's
    HttpDatasetReaderGateway (platform_gateway/http/) - that adapter exists
    because simulator-worker is a separate process that can only reach
    aria-api's datasets over HTTP. This process *is* aria-api, so it samples
    the dataset directly through the existing GetDatasetRowsUseCase instead
    of looping a call back to itself. Backs the /preview endpoint's
    SEED_RECREATION field kind."""

    def __init__(self) -> None:
        self._use_case = GetDatasetRowsUseCase(
            get_dataset_repository(), get_dataset_summary_repository()
        )

    def sample_row(self, dataset_name: str, rng: random.Random) -> dict | None:
        try:
            page = self._use_case.execute(
                GetDatasetRowsInput(
                    name=dataset_name, offset=0, limit=_DATASET_SAMPLE_WINDOW
                )
            )
        except FileNotFoundError:
            return None

        if page.total == 0:
            return None
        if page.total <= len(page.rows):
            return rng.choice(page.rows)

        offset = rng.randrange(page.total)
        second_page = self._use_case.execute(
            GetDatasetRowsInput(name=dataset_name, offset=offset, limit=1)
        )
        return second_page.rows[0] if second_page.rows else None


# --- stateless adapters: one instance per API process ---


@lru_cache
def get_simulation_scenario_repository() -> SimulationScenarioRepository:
    return DynamoSimulationScenarioRepository()


@lru_cache
def get_simulation_dispatcher() -> SimulationDispatcher:
    # Lazy import - keeps the event-simulator's Celery app out of the API
    # process's import graph until a scenario is actually started, matching
    # dataset_factory.py::get_dataset_analysis_dispatcher's lazy-import
    # pattern for its own Celery-backed dispatcher.
    from src.infrastructure.queues.celery.simulation_dispatcher import (
        CelerySimulationDispatcher,
    )

    return CelerySimulationDispatcher()


@lru_cache
def get_dataset_reader_gateway() -> DatasetReaderGateway:
    return LocalDatasetReaderGateway()


# --- use cases: fresh instance per call, wired from the singletons above ---


def get_create_simulation_scenario_use_case() -> CreateSimulationScenarioUseCase:
    return CreateSimulationScenarioUseCase(
        get_simulation_scenario_repository(),
        get_alert_schema_repository(),
    )


def get_seed_simulation_from_dataset_use_case() -> SeedSimulationFromDatasetUseCase:
    return SeedSimulationFromDatasetUseCase(
        get_dataset_repository(), get_alert_schema_repository()
    )


def get_update_simulation_scenario_use_case() -> UpdateSimulationScenarioUseCase:
    return UpdateSimulationScenarioUseCase(get_simulation_scenario_repository())


def get_get_simulation_scenario_use_case() -> GetSimulationScenarioUseCase:
    return GetSimulationScenarioUseCase(get_simulation_scenario_repository())


def get_list_simulation_scenarios_use_case() -> ListSimulationScenariosUseCase:
    return ListSimulationScenariosUseCase(get_simulation_scenario_repository())


def get_delete_simulation_scenario_use_case() -> DeleteSimulationScenarioUseCase:
    return DeleteSimulationScenarioUseCase(get_simulation_scenario_repository())


def get_start_simulation_use_case() -> StartSimulationUseCase:
    return StartSimulationUseCase(
        scenario_repository=get_simulation_scenario_repository(),
        dispatcher=get_simulation_dispatcher(),
    )


def get_pause_simulation_use_case() -> PauseSimulationUseCase:
    return PauseSimulationUseCase(get_simulation_scenario_repository())


def get_stop_simulation_use_case() -> StopSimulationUseCase:
    return StopSimulationUseCase(get_simulation_scenario_repository())


def get_get_simulation_status_use_case() -> GetSimulationStatusUseCase:
    return GetSimulationStatusUseCase(get_simulation_scenario_repository())


def get_generate_event_batch_use_case() -> GenerateEventBatchUseCase:
    return GenerateEventBatchUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        dataset_reader=get_dataset_reader_gateway(),
    )
