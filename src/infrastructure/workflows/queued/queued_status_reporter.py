from __future__ import annotations

import logging
import queue
import threading

from src.application.ports.workflow_port import (
    WorkflowExecutionRepository,
    WorkflowStepExecutionRepository,
)
from src.application.ports.workflow_status_port import (
    WorkflowStatusReporter,
    WorkflowStatusUpdate,
)

logger = logging.getLogger(__name__)

_Key = tuple[str, str | None]


class QueuedWorkflowStatusReporter(WorkflowStatusReporter):
    """In-process, single-writer status reporter, scoped to one workflow run.

    One instance per Celery task invocation - create it in
    AlertReviewWorkflowRunner.run and stop() it before returning, don't
    make it a process-wide singleton. report() only touches an in-memory
    dict plus a one-slot wakeup queue, so it never blocks on DynamoDB I/O.
    A single daemon thread applies the latest pending update per
    (workflow, step) key on each drain cycle: a burst of progress reports
    for the same key collapses into one write, and because there is
    exactly one writer processing strictly in drain order, there is no
    network-level reordering to guard against.
    """

    def __init__(
        self,
        workflow_repository: WorkflowExecutionRepository,
        step_repository: WorkflowStepExecutionRepository,
    ) -> None:
        self._workflows = workflow_repository
        self._steps = step_repository
        self._lock = threading.Lock()
        self._pending: dict[_Key, WorkflowStatusUpdate] = {}
        self._wakeup: queue.Queue[None] = queue.Queue(maxsize=1)
        self._idle = threading.Event()
        self._idle.set()
        self._stopped = False
        self._thread = threading.Thread(
            target=self._run, name="workflow-status-writer", daemon=True
        )
        self._thread.start()

    def report(self, update: WorkflowStatusUpdate) -> None:
        key: _Key = (str(update.workflow_execution_id), update.step_name)
        with self._lock:
            self._pending[key] = update
            self._idle.clear()
        try:
            self._wakeup.put_nowait(None)
        except queue.Full:
            pass  # writer is already scheduled to wake and will see the update

    def flush(self, timeout: float | None = None) -> None:
        self._idle.wait(timeout)

    def stop(self, timeout: float | None = 5.0) -> None:
        self.flush(timeout)
        self._stopped = True
        try:
            self._wakeup.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout)

    def _run(self) -> None:
        while not self._stopped:
            self._wakeup.get()
            self._drain()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._idle.set()
                    return
                key, update = self._pending.popitem()
            self._write(update)

    def _write(self, update: WorkflowStatusUpdate) -> None:
        detail = update.detail or {}
        try:
            if update.step_name is None:
                self._workflows.update(
                    update.workflow_execution_id,
                    status=update.status,
                    **detail,
                )
                return
            if update.step_id is None:
                logger.warning(
                    "Dropping step status update without step_id: "
                    "workflow=%s step=%s",
                    update.workflow_execution_id,
                    update.step_name,
                )
                return
            self._steps.update(
                update.workflow_execution_id,
                update.step_id,
                status=update.status,
                **detail,
            )
        except Exception:
            logger.exception(
                "Failed writing workflow status update: workflow=%s step=%s",
                update.workflow_execution_id,
                update.step_name,
            )
