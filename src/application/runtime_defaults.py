"""Runtime dependency defaults for directly constructed use cases.

Production factories inject infrastructure adapters. The defaults keep small
application use cases usable in scripts and preserve compatibility with older
callers that still pass a zero argument clock function.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.application.ports.clock_port import Clock
from src.application.ports.id_generator_port import IdGenerator


class _DefaultClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class _CallableClock(Clock):
    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock

    def now(self) -> datetime:
        return self._clock()


class _DefaultIdGenerator(IdGenerator):
    def new_id(self) -> UUID:
        return uuid4()


DEFAULT_CLOCK: Clock = _DefaultClock()
DEFAULT_ID_GENERATOR: IdGenerator = _DefaultIdGenerator()


def resolve_clock(clock: Clock | Callable[[], datetime] | None) -> Clock:
    if clock is None:
        return DEFAULT_CLOCK
    if isinstance(clock, Clock):
        return clock
    if callable(clock):
        return _CallableClock(clock)
    raise TypeError("clock must implement Clock or be a zero argument callable")
