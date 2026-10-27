from __future__ import annotations

import re

from src.application.ports.personal_data_masker_port import (
    MaskedPersonalData,
    PersonalDataMasker,
)

_PATTERNS: tuple[tuple[str, re.Pattern[str], str | None], ...] = (
    (
        "NIT",
        re.compile(
            r"(?i)\bnit\s*(?:no\.?|n[uú]m(?:ero)?\.?)?\s*[:#-]?\s*"
            r"(?P<value>\d{3}[. ]?\d{3}[. ]?\d{3}[- ]?\d?)\b"
        ),
        "value",
    ),
    (
        "NIT",
        re.compile(r"(?<!\d)\d{3}[. ]?\d{3}[. ]?\d{3}[- ]\d(?!\d)"),
        None,
    ),
    (
        "TEL",
        re.compile(r"(?<!\d)(?:\+?57[ .-]?)?3\d{2}[ .-]?\d{3}[ .-]?\d{4}(?!\d)"),
        None,
    ),
    (
        "CUENTA",
        re.compile(
            r"(?i)\b(?:cuenta|n[uú]mero de cuenta|cta\.?|account)\s*"
            r"(?:no\.?|n[uú]m(?:ero)?\.?)?\s*[:#-]?\s*"
            r"(?P<value>\d(?:[ .-]?\d){7,19})"
        ),
        "value",
    ),
    ("TARJETA", re.compile(r"(?<!\d)(?:\d[ .-]?){12,18}\d(?!\d)"), None),
    (
        "CC",
        re.compile(
            r"(?i)\b(?:c\.c\.?|cc|c[eé]dula|documento|identificaci[oó]n)"
            r"\s*(?:no\.?|n[uú]m(?:ero)?\.?)?\s*[:#-]?\s*"
            r"(?P<value>\d(?:[ .-]?\d){5,10})"
        ),
        "value",
    ),
    ("EMAIL", re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?!\w)"), None),
    ("IP", re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"), None),
    ("CC", re.compile(r"(?<!\d)\d{1,3}(?:\.\d{3}){2,3}(?!\d)"), None),
    (
        "PERSONA",
        re.compile(
            r"(?i)\b(?:nombre(?: del cliente)?|titular)\s*[:=-]\s*"
            r"(?P<value>[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+"
            r"(?:\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñ]+){0,3})"
        ),
        "value",
    ),
)


class RuleBasedPersonalDataMasker(PersonalDataMasker):
    """Request-local reversible masking of common Colombian identifiers."""

    def mask(self, text: str) -> MaskedPersonalData:
        candidates: list[tuple[int, int, str]] = []
        for label, pattern, group in _PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.span(group) if group else match.span()
                if label == "IP" and not _valid_ipv4(match.group()):
                    continue
                candidates.append((start, end, label))

        candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
        selected: list[tuple[int, int, str]] = []
        cursor = -1
        for candidate in candidates:
            if candidate[0] >= cursor:
                selected.append(candidate)
                cursor = candidate[1]

        counts: dict[str, int] = {}
        replacements: dict[str, str] = {}
        chunks: list[str] = []
        cursor = 0
        for start, end, label in selected:
            chunks.append(text[cursor:start])
            counts[label] = counts.get(label, 0) + 1
            token = f"[{label}_{counts[label]}]"
            chunks.append(token)
            replacements[token] = text[start:end]
            cursor = end
        chunks.append(text[cursor:])
        return MaskedPersonalData("".join(chunks), counts, replacements)

    def unmask(self, text: str, replacements: dict[str, str]) -> str:
        """Restore only the placeholders produced for this request."""
        for token, value in replacements.items():
            text = text.replace(token, value)
        return text


def _valid_ipv4(value: str) -> bool:
    try:
        return all(0 <= int(part) <= 255 for part in value.split("."))
    except ValueError:
        return False
