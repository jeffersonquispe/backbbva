from __future__ import annotations

from functools import lru_cache

from src.application.ports.metrics_rollup_port import MetricsRollupRepository
from src.application.use_cases.metrics.get_agent_metrics import GetAgentMetrics
from src.application.use_cases.metrics.get_live_alert_funnel import (
    GetLiveAlertFunnel,
)
from src.application.use_cases.metrics.get_metrics_overview import GetMetricsOverview
from src.application.use_cases.metrics.get_technical_metrics import (
    GetTechnicalMetrics,
)
from src.application.use_cases.metrics.get_version_events import GetVersionEvents
from src.application.use_cases.metrics.record_alert_metrics_event import (
    RecordAlertMetricsEvent,
)
from src.infrastructure.core.config import genai_config
from src.infrastructure.core.runtime.system_clock import get_clock
from src.infrastructure.entrypoint.api.factories.alert_factory import (
    get_alert_repository,
)
from src.infrastructure.entrypoint.api.factories.alert_schema_factory import (
    get_alert_schema_repository,
)
from src.infrastructure.entrypoint.api.factories.configuration_factory import (
    get_configuration_repository,
)
from src.infrastructure.entrypoint.api.factories.operational_settings_factory import (
    get_operational_settings_repository,
)
from src.infrastructure.entrypoint.api.metrics_query_cache import (
    CachedMetricsQuery,
    get_metrics_query_cache,
)
from src.infrastructure.monitoring.opentelemetry import get_monitoring
from src.infrastructure.persistence.database.dynamodb.repositories.alert_schema_repository import (
    DynamoAlertSchemaRepository,
)
from src.infrastructure.persistence.database.dynamodb.repositories.metrics_rollup_repository import (
    DynamoMetricsRollupRepository,
)


@lru_cache
def get_metrics_rollup_repository() -> MetricsRollupRepository:
    return DynamoMetricsRollupRepository(timezone_name=genai_config.OPERATIONS_TIMEZONE)


def get_record_alert_metrics_event_use_case() -> RecordAlertMetricsEvent:
    return RecordAlertMetricsEvent(
        alert_repository=get_alert_repository(),
        rollup_repository=get_metrics_rollup_repository(),
        settings_repository=get_operational_settings_repository(),
        schema_repository=DynamoAlertSchemaRepository(),
        timezone_name=genai_config.OPERATIONS_TIMEZONE,
        monitoring=get_monitoring(),
        clock=get_clock(),
    )


def get_metrics_overview_use_case() -> CachedMetricsQuery:
    # A4: served through the 60 s per-query cache (metrics_query_cache.py).
    return CachedMetricsQuery(
        "overview",
        GetMetricsOverview(
            rollup_repository=get_metrics_rollup_repository(),
            timezone_name=genai_config.OPERATIONS_TIMEZONE,
            clock=get_clock(),
            operational_settings_repository=get_operational_settings_repository(),
        ),
        get_metrics_query_cache(),
    )


def get_agent_metrics_use_case() -> CachedMetricsQuery:
    # A4: served through the 60 s per-query cache (metrics_query_cache.py).
    return CachedMetricsQuery(
        "agent",
        GetAgentMetrics(
            rollup_repository=get_metrics_rollup_repository(),
            timezone_name=genai_config.OPERATIONS_TIMEZONE,
            clock=get_clock(),
            operational_settings_repository=get_operational_settings_repository(),
        ),
        get_metrics_query_cache(),
    )


def get_live_alert_funnel_use_case() -> GetLiveAlertFunnel:
    # Imported here: operations_factory imports this module (circular).
    from src.infrastructure.entrypoint.api.factories.operations_factory import (
        get_resource_reservation_repository,
    )

    return GetLiveAlertFunnel(
        alert_repository=get_alert_repository(),
        reservation_repository=get_resource_reservation_repository(),
        clock=get_clock(),
    )


def get_technical_metrics_use_case() -> CachedMetricsQuery:
    # A4: served through the 60 s per-query cache (metrics_query_cache.py).
    return CachedMetricsQuery(
        "technical",
        GetTechnicalMetrics(
            rollup_repository=get_metrics_rollup_repository(),
            timezone_name=genai_config.OPERATIONS_TIMEZONE,
            clock=get_clock(),
            operational_settings_repository=get_operational_settings_repository(),
        ),
        get_metrics_query_cache(),
    )


def get_version_events_use_case() -> GetVersionEvents:
    return GetVersionEvents(
        schema_repository=get_alert_schema_repository(),
        configuration_repository=get_configuration_repository(),
        clock=get_clock(),
    )
