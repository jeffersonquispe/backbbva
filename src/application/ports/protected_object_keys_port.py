from __future__ import annotations

from abc import ABC


class ProtectedObjectKeysPort(ABC):
    def protected_object_keys(self) -> frozenset[str]:
        """Archive objects that retention sweeps must not delete (legal hold)."""
        raise NotImplementedError
