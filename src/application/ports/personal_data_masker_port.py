from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class MaskedPersonalData:
    text: str
    counts: dict[str, int]


class PersonalDataMasker(ABC):
    @abstractmethod
    def mask(self, text: str) -> MaskedPersonalData:
        raise NotImplementedError
