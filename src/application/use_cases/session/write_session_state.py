from __future__ import annotations

from application.dtos.session_dtos import WriteSessionStateInput, ReadSessionStateOutput
from application.ports.session_port import SessionStateStorePort


class WriteSessionStateUseCase:
    def __init__(self, kv_store: SessionStateStorePort) -> None:
        self._kv = kv_store

    def execute(self, input: WriteSessionStateInput) -> ReadSessionStateOutput:
        self._kv.set(input.key, input.value, ttl_seconds=input.ttl_seconds)
        return ReadSessionStateOutput(
            key=input.key,
            value=input.value,
            exists=True,
        )
