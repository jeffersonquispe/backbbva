import os

from genai.libs.observability import setup_observability
from opentelemetry import metrics
from opentelemetry.sdk.resources import SERVICE_INSTANCE_ID

# TAKE CARE: I have added the alias cfg to config since within the config
# file there can be the config attribute which is expected to be a path.
from src.infrastructure.core.config import genai_config as cfg

bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 300
keepalive = 75


def _worker_count() -> int:
    # Honour an explicit override set in the ECS task definition or compose file.
    if (env := os.getenv("GUNICORN_WORKERS")):
        return int(env)
    # sched_getaffinity(0) reads the cgroup CPU-set — the correct value inside a
    # container. cpu_count() would return the host's total cores instead.
    try:
        cores = len(os.sched_getaffinity(0))
    except AttributeError:
        cores = os.cpu_count() or 1
    # For async I/O-bound workers one extra process adds fault tolerance without
    # the memory cost of the 2*N formula designed for blocking sync workers.
    # Cap at 4: each worker loads LLM clients + connection pools into memory.
    return min(cores + 1, 4)


workers = _worker_count()


def post_fork(server, worker):

    worker_pid = worker.pid
    application = cfg.GENAI_PRODUCT
    product = cfg.GENAI_NAME
    service_name = cfg.GENAI_NAME
    service_instance_id = cfg.ECS_CONTAINER_METADATA_URI_V4.rsplit("/", 1)[
        -1
    ].split("-")[0]

    setup_observability(
        cfg.GENAI_ENVIRONMENT,
        {
            "service.name": cfg.GENAI_NAME,
            SERVICE_INSTANCE_ID: service_instance_id,
            "worker": worker_pid,
            "AppRunner": service_name,
            "Application": application,
            "Product": product,
        },
        logging_level=cfg.DEFAULT_LOGGING_LEVEL,
        kinesis_stream=cfg.GENAI_OTEL_EXPORTER_KINESIS_STREAM,
        kinesis_obfuscate_fields=cfg.GENAI_OTEL_EXPORTER_KINESIS_STREAM_OBFUSCATE_FIELDS,
        otlp_obfuscate_fields=cfg.GENAI_OTEL_EXPORTER_OTLP_STREAM_OBFUSCATE_FIELDS,
    )

    meter = metrics.get_meter(__name__)
    # Crea una métrica de contador con el mismo nombre que en CloudWatch
    counter = meter.create_counter(
        name="gunicorn.worker",  # Reemplaza "MetricName" con el nombre de tu métrica
        description="",
        unit="count",  # Reemplaza "Unit" con la unidad de tu métrica
    )

    counter.add(1)

    server.log.info(
        f"Worker dev spawned (instance-id: {service_instance_id} pid: {worker.pid})"
    )
