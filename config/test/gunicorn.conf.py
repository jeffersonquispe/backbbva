from genai.libs.observability import setup_logging

# TAKE CARE: I have added the alias cfg to config since within the config
# file there can be the config attribute which is expected to be a path.
from src.infrastructure.core.config import genai_config as cfg

bind = "0.0.0.0:8000"
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 300
keepalive = 75


def post_fork(server, worker):
    service_instance_id = "test"
    setup_logging(logging_level=cfg.DEFAULT_LOGGING_LEVEL)
    server.log.info(
        f"Worker test spawned (instance-id: {service_instance_id} pid: {worker.pid})"
    )
