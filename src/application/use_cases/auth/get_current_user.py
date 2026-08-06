from __future__ import annotations

from application.dtos.auth_dtos import GetCurrentUserInput, UserOutput
from application.ports.auth_port import SessionRepository, UserRepository


class GetCurrentUserUseCase:
    def __init__(
        self,
        session_repo: SessionRepository,
        user_repo: UserRepository,
    ) -> None:
        self._session_repo = session_repo
        self._user_repo = user_repo

    def execute(self, input: GetCurrentUserInput) -> UserOutput:
        session = self._session_repo.get_by_token(input.session_token)
        if session is None:
            raise PermissionError("Session not found or invalid.")
        if session.is_expired():
            raise PermissionError("Session has expired.")

        user = self._user_repo.get_by_id(session.user_id)
        if user is None:
            raise LookupError(f"User not found: {session.user_id}")

        return UserOutput(
            id=user.id,
            email=user.email,
            name=user.name,
            given_name=user.given_name,
            avatar_url=user.avatar_url,
            auth_provider=user.auth_provider,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )
