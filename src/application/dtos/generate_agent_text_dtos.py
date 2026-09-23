from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GenerateAgentTextInput:
    # Already {variable}-substituted (see substitute_variables) - this use
    # case is a plain single-shot LLM call, it doesn't know about the
    # alert's field names or the segment's enrichment recipes.
    prompt: str


@dataclass
class GenerateAgentTextOutput:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
