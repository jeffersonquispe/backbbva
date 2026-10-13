from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from src.application.ports.local_auth_port import LocalUser
from src.infrastructure.core.config import genai_config


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class PasswordHasher:
    _iterations = 600_000

    def hash(self, password: str) -> str:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt, self._iterations
        )
        return (
            f"pbkdf2_sha256${self._iterations}${_b64encode(salt)}${_b64encode(digest)}"
        )

    def verify(self, password: str, encoded: str) -> bool:
        try:
            scheme, iterations, salt, expected = encoded.split("$")
            if scheme != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode(), _b64decode(salt), int(iterations)
            )
            return hmac.compare_digest(actual, _b64decode(expected))
        except (TypeError, ValueError):
            return False


class JwtService:
    def __init__(
        self, secret: str | None = None, ttl_seconds: int | None = None
    ) -> None:
        self._secret = (secret or genai_config.AUTH_JWT_SECRET).encode()
        self._ttl_seconds = ttl_seconds or genai_config.AUTH_JWT_TTL_SECONDS

    def issue(self, user: LocalUser) -> tuple[str, int]:
        now = int(datetime.now(UTC).timestamp())
        header = _b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode()
        )
        payload = _b64encode(
            json.dumps(
                {
                    "sub": str(user.id),
                    "jti": uuid4().hex,
                    "email": user.email,
                    "role": user.role.value,
                    "iat": now,
                    "exp": now + self._ttl_seconds,
                },
                separators=(",", ":"),
            ).encode()
        )
        signature = _b64encode(
            hmac.new(
                self._secret, f"{header}.{payload}".encode(), hashlib.sha256
            ).digest()
        )
        return f"{header}.{payload}.{signature}", self._ttl_seconds

    def decode(self, token: str) -> dict:
        try:
            header, payload, signature = token.split(".")
            expected = hmac.new(
                self._secret, f"{header}.{payload}".encode(), hashlib.sha256
            ).digest()
            if not hmac.compare_digest(expected, _b64decode(signature)):
                raise ValueError
            claims = json.loads(_b64decode(payload))
            if int(claims["exp"]) <= int(datetime.now(UTC).timestamp()):
                raise ValueError
            UUID(claims["sub"])
            return claims
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ValueError("Invalid or expired access token") from None
