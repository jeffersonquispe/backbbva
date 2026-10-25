from __future__ import annotations

from functools import lru_cache

import jwt
from jwt import PyJWKClient

from src.infrastructure.entrypoint.event_api.settings import event_api_settings


class OidcTokenVerifier:
    def __init__(
        self, issuer: str, audience: str, jwks_url: str, allowed_client_id: str
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._allowed_client_id = allowed_client_id
        self._jwks = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=300)

    def verify(self, token: str) -> dict:
        signing_key = self._jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        if claims.get("azp", claims.get("client_id")) != self._allowed_client_id:
            raise jwt.InvalidTokenError("OIDC client is not authorized")
        return claims


@lru_cache
def get_oidc_verifier() -> OidcTokenVerifier:
    settings = event_api_settings()
    return OidcTokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        jwks_url=settings.oidc_jwks_url,
        allowed_client_id=settings.oidc_allowed_client_id,
    )
