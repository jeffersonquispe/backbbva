from __future__ import annotations

from application.dtos.session_dtos import DeleteSessionStateInput
from application.ports.session_port import SessionStateStorePort


class DeleteSessionStateUseCase:
    def __init__(self, kv_store: SessionStateStorePort) -> None:
        self._kv = kv_store

    def execute(self, input: DeleteSessionStateInput) -> None:
        self._kv.delete(input.key)
