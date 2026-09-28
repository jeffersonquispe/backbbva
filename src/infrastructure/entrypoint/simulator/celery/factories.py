from __future__ import annotations

from functools import lru_cache

from src.application.ports.alert_dispatch_gateway_port import AlertDispatchGateway
from src.application.ports.dataset_reader_gateway_port import DatasetReaderGateway
from src.application.ports.event_sink_port import EventSink
from src.application.use_cases.event_simulation.generate_event_batch import (
    GenerateEventBatchUseCase,
)
from src.application.use_cases.event_simulation.record_tick_result import (
    RecordTickResultUseCase,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.simulation_scenario_repository import (
    DynamoSimulationScenarioRepository,
)

# --- stateless adapters: one instance per worker process ---


@lru_cache
def get_simulation_scenario_repository() -> DynamoSimulationScenarioRepository:
    return DynamoSimulationScenarioRepository()


def _aria_api_base_url() -> str:
    # aria-api mounts alerts_router/datasets_router under API_V0_STR (see
    # fastapi_app.py) - EVENT_SIMULATOR_ARIA_API_BASE_URL is just host:port,
    # so every Http* gateway needs the version prefix appended too.
    return genai_config.EVENT_SIMULATOR_ARIA_API_BASE_URL + genai_config.API_V0_STR


@lru_cache
def get_alert_dispatch_gateway() -> AlertDispatchGateway:
    from src.infrastructure.platform_gateway.http.http_alert_dispatch_gateway import (
        HttpAlertDispatchGateway,
    )

    return HttpAlertDispatchGateway(
        base_url=_aria_api_base_url(),
        token=genai_config.EVENT_SIMULATOR_ARIA_API_TOKEN or None,
    )


@lru_cache
def get_event_sink() -> EventSink:
    from src.infrastructure.platform_gateway.http.http_event_sink import (
        HttpEventSink,
    )

    return HttpEventSink(
        base_url=_aria_api_base_url(),
        token=genai_config.EVENT_SIMULATOR_ARIA_API_TOKEN or None,
    )


@lru_cache
def get_dataset_reader_gateway() -> DatasetReaderGateway:
    from src.infrastructure.platform_gateway.http.http_dataset_reader_gateway import (
        HttpDatasetReaderGateway,
    )

    return HttpDatasetReaderGateway(
        base_url=_aria_api_base_url(),
        token=genai_config.EVENT_SIMULATOR_ARIA_API_TOKEN or None,
    )


# --- use cases: fresh instance per call, wired from the singletons above ---


def get_generate_event_batch_use_case() -> GenerateEventBatchUseCase:
    return GenerateEventBatchUseCase(
        llm_unit_of_work_factory=get_llm_unit_of_work_factory(),
        monitoring=get_monitoring(),
        dataset_reader=get_dataset_reader_gateway(),
    )


def get_record_tick_result_use_case() -> RecordTickResultUseCase:
    return RecordTickResultUseCase(get_simulation_scenario_repository())
