from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MaskedPersonalData:
    """Masked text plus a request-scoped restoration map; never persist replacements."""

    text: str
    counts: dict[str, int]
    replacements: dict[str, str] = field(default_factory=dict, repr=False, compare=False)


class PersonalDataMasker(ABC):
    @abstractmethod
    def mask(self, text: str) -> MaskedPersonalData:
        raise NotImplementedError

    def unmask(self, text: str, replacements: dict[str, str]) -> str:
        """Restore placeholders in an LLM response using request-local data."""
        for token, value in replacements.items():
            text = text.replace(token, value)
        return text
