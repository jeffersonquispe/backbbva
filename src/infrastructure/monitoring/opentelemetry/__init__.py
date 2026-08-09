from functools import lru_cache

from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.monitoring.opentelemetry.monitoring import (
    OpenTelemetryMonitoring,
)
from src.infrastructure.monitoring.opentelemetry.tracer import get_tracer


@lru_cache(maxsize=1)
def get_monitoring() -> MonitoringPort:
    return OpenTelemetryMonitoring(get_tracer())
