from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ReadSessionStateInput:
    key: str


@dataclass
class ReadSessionStateOutput:
    key: str
    value: Optional[str]
    exists: bool


@dataclass
class WriteSessionStateInput:
    key: str
    value: str
    ttl_seconds: Optional[int] = None


@dataclass
class DeleteSessionStateInput:
    key: str
