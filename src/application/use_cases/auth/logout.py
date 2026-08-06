from __future__ import annotations

from application.dtos.auth_dtos import LogoutInput
from application.ports.auth_port import SessionRepository


class LogoutUseCase:
    def __init__(self, session_repo: SessionRepository) -> None:
        self._session_repo = session_repo

    def execute(self, input: LogoutInput) -> None:
        self._session_repo.delete_by_token(input.session_token)
