from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class IdGenerator(ABC):
    """Creates identifiers used by application use cases."""

    @abstractmethod
    def new_id(self) -> UUID:
        raise NotImplementedError
