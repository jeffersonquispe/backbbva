from __future__ import annotations

from abc import ABC
from uuid import UUID


class SimulationDispatcher(ABC):
    """Kicks off (or resumes) a scenario's self-rescheduling tick loop - see
    infrastructure/entrypoint/simulator/celery/ for the Celery adapter and
    tasks.py's event_simulation.tick for what actually runs on each tick."""

    def dispatch(self, scenario_id: UUID) -> None:
        raise NotImplementedError
