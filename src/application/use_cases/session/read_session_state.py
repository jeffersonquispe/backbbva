from __future__ import annotations

from application.dtos.session_dtos import ReadSessionStateInput, ReadSessionStateOutput
from application.ports.session_port import SessionStateStorePort


class ReadSessionStateUseCase:
    def __init__(self, kv_store: SessionStateStorePort) -> None:
        self._kv = kv_store

    def execute(self, input: ReadSessionStateInput) -> ReadSessionStateOutput:
        value = self._kv.get(input.key)
        return ReadSessionStateOutput(
            key=input.key,
            value=value,
            exists=value is not None,
        )
