from src.application.ports.global_pipeline_evaluation_port import (
    GlobalPipelineEvaluationDispatcher,
)
from src.infrastructure.queues.celery.app import agent_app


class CeleryGlobalPipelineEvaluationDispatcher(GlobalPipelineEvaluationDispatcher):
    def dispatch(self, snapshot_id: str) -> None:
        agent_app.send_task(
            "optimizer.evaluate_global_pipeline",
            args=[snapshot_id],
            queue=agent_app.conf.task_default_queue,
        )
