from __future__ import annotations

from typing import Optional, Protocol


class SessionStateStorePort(Protocol):
    def get(self, key: str) -> Optional[str]: ...

    def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> None: ...

    def delete(self, key: str) -> None: ...
