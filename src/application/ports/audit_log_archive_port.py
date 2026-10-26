from __future__ import annotations

from typing import Any, Protocol


class AuditLogArchivePort(Protocol):
    def flush(self, *, max_hot_items: int, retention_days: int) -> dict[str, int]: ...

    def query(
        self,
        *,
        from_date: str,
        to_date: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...
