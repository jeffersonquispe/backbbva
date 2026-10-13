from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    """Supplies the current instant to application use cases."""

    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError
