from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import Optional

from application.dtos.auth_dtos import OAuthCallbackInput, AuthSessionOutput
from application.ports.auth_port import (
    AuthStoragePort,
    IdentityPort,
    OrganizationRecord,
    OrganizationRepository,
    OrganizationRole,
    SessionRecord,
    SessionRepository,
    UserOrganizationRecord,
    UserOrganizationRepository,
    UserRecord,
    UserRepository,
)


class OAuthCallbackUseCase:
    """
    Handles OAuth2 callback: exchanges code for tokens, upserts user,
    creates default org if new user, sets up infrastructure, creates session.
    """

    def __init__(
        self,
        identity_port: IdentityPort,
        storage_port: AuthStoragePort,
        user_repo: UserRepository,
        organization_repo: OrganizationRepository,
        user_org_repo: UserOrganizationRepository,
        session_repo: SessionRepository,
    ) -> None:
        self._identity_port = identity_port
        self._storage_port = storage_port
        self._user_repo = user_repo
        self._organization_repo = organization_repo
        self._user_org_repo = user_org_repo
        self._session_repo = session_repo

    def execute(self, input: OAuthCallbackInput) -> AuthSessionOutput:
        # 1. Exchange code for tokens
        tokens = self._identity_port.exchange_code_for_tokens(input.code, input.redirect_uri)

        # 2. Decode id token to get user identity
        info = self._identity_port.decode_id_token(tokens.id_token)

        # 3. Upsert user
        now = datetime.utcnow()
        user = self._user_repo.get_by_cognito_sub(info.sub)
        is_new_user = user is None

        if is_new_user:
            user_id = uuid.uuid4()
            user = UserRecord(
                id=user_id,
                cognito_sub=info.sub,
                email=info.email,
                name=info.name,
                given_name=info.given_name,
                avatar_url=info.picture,
                auth_provider=info.provider,
                is_active=True,
                created_at=now,
                updated_at=now,
                created_by=None,
                updated_by=None,
            )
            user = self._user_repo.create(user)

        # 4. If new user, create default org and infrastructure
        org: Optional[OrganizationRecord] = None
        if is_new_user:
            org_id = uuid.uuid4()
            org = OrganizationRecord(
                id=org_id,
                name=f"{info.name}'s Organization",
                active=True,
                created_at=now,
                updated_at=now,
                created_by=user.id,
                updated_by=None,
            )
            org = self._organization_repo.create(org)

            user_org = UserOrganizationRecord(
                id=uuid.uuid4(),
                user_id=user.id,
                organization_id=org.id,
                organization_name=org.name,
                role=OrganizationRole.ADMIN,
                created_at=now,
                updated_at=now,
                created_by=user.id,
                updated_by=None,
            )
            self._user_org_repo.create(user_org)

            self._storage_port.create_directory(f"app_files/organization_{org.id}/")
            self._identity_port.create_organization_groups(str(org.id))
        else:
            # Get the user's primary organization
            user_orgs = self._user_org_repo.list_by_user(user.id)
            if user_orgs:
                org = self._organization_repo.get_by_id(user_orgs[0].organization_id)

        # 5. Create session
        session_token = secrets.token_urlsafe(64)
        session = SessionRecord(
            id=uuid.uuid4(),
            user_id=user.id,
            session_token=session_token,
            expires_at=now + timedelta(hours=24),
            created_at=now,
            updated_at=now,
        )
        self._session_repo.create(session)

        # 6. Return output
        organization_id = str(org.id) if org else ""
        return AuthSessionOutput(
            session_token=session_token,
            user_id=str(user.id),
            email=user.email,
            name=user.name,
            organization_id=organization_id,
        )
