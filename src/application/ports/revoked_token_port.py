from __future__ import annotations

from datetime import datetime
from typing import Protocol


class RevokedTokenRepository(Protocol):
    """Denylist of access tokens ended by logout before their expiry.

    Keyed by the token's ``jti`` claim. An entry only needs to live until the
    token's own ``exp`` - after that the signature check rejects it anyway.
    """

    def revoke(self, token_id: str, expires_at: datetime) -> None: ...
    def is_revoked(self, token_id: str) -> bool: ...
