"""Framework-free {variable} substitution for segment-authored prompt text."""

from __future__ import annotations

import re
from typing import Any

_TOKEN = re.compile(r"\{(\w+)\}")


def substitute_variables(text: str, variables: dict[str, Any]) -> str:
    """Replace {name} with str(variables[name]); an unknown name is left
    literal (a config typo must never surface as a crash or a silently
    dropped token) - deliberately not str.format, which raises on any
    stray brace in free-form prompt text."""
    return _TOKEN.sub(
        lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0),
        text,
    )
