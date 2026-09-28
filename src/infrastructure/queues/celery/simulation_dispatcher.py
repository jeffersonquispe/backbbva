from __future__ import annotations

from uuid import UUID

from src.application.ports.simulation_dispatcher_port import SimulationDispatcher


class CelerySimulationDispatcher(SimulationDispatcher):
    """Kicks off a scenario's self-rescheduling tick loop by enqueuing its
    very first tick onto the event-simulator's own Celery broker/queue - see
    entrypoint/simulator/celery/tasks.py's event_simulation.tick for the loop
    itself, which runs in the separate simulator-worker process/pod. Backs
    StartSimulationUseCase, same import-the-target-task-and-call pattern as
    this package's other dispatchers (dispatcher.py -> aria-worker's task)."""

    def dispatch(self, scenario_id: UUID) -> None:
        from src.infrastructure.entrypoint.simulator.celery.tasks import tick

        tick.apply_async(args=[str(scenario_id)])
