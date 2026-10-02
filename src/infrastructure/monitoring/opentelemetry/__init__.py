from functools import lru_cache

from src.application.ports.monitoring_port import MonitoringPort
from src.infrastructure.monitoring.opentelemetry.log_handler import (
    install_otlp_logging,
)
from src.infrastructure.monitoring.opentelemetry.meter import get_meter
from src.infrastructure.monitoring.opentelemetry.monitoring import (
    OpenTelemetryMonitoring,
)
from src.infrastructure.monitoring.opentelemetry.tracer import get_tracer


@lru_cache(maxsize=1)
def get_monitoring() -> MonitoringPort:
    # Logs ride along with traces/metrics: whichever process (API or worker)
    # first asks for monitoring also starts shipping its log records over
    # OTLP. No-op when OTEL_ENDPOINT is empty.
    install_otlp_logging()
    return OpenTelemetryMonitoring(get_tracer(), get_meter())
