from datetime import UTC, datetime
from functools import lru_cache

from src.application.ports.clock_port import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


@lru_cache(maxsize=1)
def get_clock() -> Clock:
    return SystemClock()
