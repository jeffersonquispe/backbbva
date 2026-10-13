from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics.view import (
    ExplicitBucketHistogramAggregation,
    View,
)

from src.infrastructure.core.config import genai_config
from src.infrastructure.monitoring.opentelemetry.resource import (
    build_resource,
    otel_export_enabled,
)

# Instrument names (OTel GenAI semconv for gen_ai.*; aria.* are ours).
# Prometheus names after the Collector: dots -> underscores, plus unit suffix
# (`_seconds`) and `_total` for counters, e.g.
# gen_ai_client_operation_duration_seconds_bucket, aria_research_calls_total.
GEN_AI_TOKEN_USAGE = "gen_ai.client.token.usage"
GEN_AI_OPERATION_DURATION = "gen_ai.client.operation.duration"
ARIA_WORKFLOW_DURATION = "aria.workflow.duration"
ARIA_RESEARCH_CALLS = "aria.research.calls"
ARIA_ROLLUP_DRIFT = "aria.metrics.rollup_drift"
ARIA_AGENT_ENABLED = "aria.agent.enabled"
ARIA_OPERATING_HOURS = "aria.operating_hours"
ARIA_ANALYST_QUEUE_DEPTH = "aria.analyst_queue.depth"
ARIA_ANALYST_QUEUE_OLDEST_AGE = "aria.analyst_queue.oldest_age"
ARIA_CAPACITY_AVAILABLE = "aria.capacity.available"

# Bucket boundaries recommended by the GenAI semantic conventions.
_GEN_AI_DURATION_BUCKETS = (
    0.01,
    0.02,
    0.04,
    0.08,
    0.16,
    0.32,
    0.64,
    1.28,
    2.56,
    5.12,
    10.24,
    20.48,
    40.96,
    81.92,
)
_GEN_AI_TOKEN_BUCKETS = (
    1,
    4,
    16,
    64,
    256,
    1024,
    4096,
    16384,
    65536,
    262144,
    1048576,
    4194304,
    16777216,
    67108864,
)
# Workflow steps/runs: seconds to tens of minutes; 300 s is the SLA line.
_WORKFLOW_DURATION_BUCKETS = (
    0.5,
    1,
    2.5,
    5,
    10,
    30,
    60,
    120,
    180,
    240,
    300,
    450,
    600,
    900,
    1800,
    3600,
)

_METRIC_EXPORT_INTERVAL_MS = 15_000


def _views() -> list[View]:
    return [
        View(
            instrument_name=GEN_AI_OPERATION_DURATION,
            aggregation=ExplicitBucketHistogramAggregation(_GEN_AI_DURATION_BUCKETS),
        ),
        View(
            instrument_name=GEN_AI_TOKEN_USAGE,
            aggregation=ExplicitBucketHistogramAggregation(_GEN_AI_TOKEN_BUCKETS),
        ),
        View(
            instrument_name=ARIA_WORKFLOW_DURATION,
            aggregation=ExplicitBucketHistogramAggregation(_WORKFLOW_DURATION_BUCKETS),
        ),
    ]


def build_meter_provider(readers: Sequence[MetricReader]) -> MeterProvider:
    return MeterProvider(
        resource=build_resource(), metric_readers=list(readers), views=_views()
    )


@lru_cache(maxsize=1)
def get_meter() -> metrics.Meter:
    readers: list[MetricReader] = []
    if otel_export_enabled():
        readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=genai_config.OTEL_ENDPOINT),
                export_interval_millis=_METRIC_EXPORT_INTERVAL_MS,
            )
        )
    provider = build_meter_provider(readers)
    metrics.set_meter_provider(provider)
    return provider.get_meter(genai_config.COMPONENT_NAME)


class AriaInstruments:
    """All explicit instruments, created once per Meter."""

    def __init__(self, meter: metrics.Meter) -> None:
        self.token_usage = meter.create_histogram(
            GEN_AI_TOKEN_USAGE,
            unit="{token}",
            description="Number of input and output tokens used per LLM call.",
        )
        self.operation_duration = meter.create_histogram(
            GEN_AI_OPERATION_DURATION,
            unit="s",
            description="Duration of GenAI client operations.",
        )
        self.workflow_duration = meter.create_histogram(
            ARIA_WORKFLOW_DURATION,
            unit="s",
            description="Duration of alert-review workflow steps and runs.",
        )
        self.research_calls = meter.create_counter(
            ARIA_RESEARCH_CALLS,
            unit="{call}",
            description="Research lookups (vector store, history) by outcome.",
        )
        self.rollup_drift = meter.create_gauge(
            ARIA_ROLLUP_DRIFT,
            unit="{row}",
            description="Drift found by the last metrics-rollup reconciliation.",
        )
        self.agent_enabled = meter.create_gauge(
            ARIA_AGENT_ENABLED,
            description="1 when the ARIA agent is ON, 0 otherwise.",
        )
        self.operating_hours = meter.create_gauge(
            ARIA_OPERATING_HOURS,
            description="1 inside the configured operating hours, else 0.",
        )
        self.analyst_queue_depth = meter.create_gauge(
            ARIA_ANALYST_QUEUE_DEPTH,
            unit="{alert}",
            description="Escalated alerts waiting for an analyst.",
        )
        self.analyst_queue_oldest_age = meter.create_gauge(
            ARIA_ANALYST_QUEUE_OLDEST_AGE,
            unit="s",
            description="Age of the oldest escalated alert not yet taken.",
        )
        self.capacity_available = meter.create_gauge(
            ARIA_CAPACITY_AVAILABLE,
            unit="{slot}",
            description="Free analyst / voicebot capacity.",
        )
