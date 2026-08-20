from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectStorageRef:
    bucket: str
    key: str
    uri: str


class ObjectStoragePort:
    def put_text(
        self,
        key: str,
        content: str,
        content_type: str = "text/plain",
    ) -> ObjectStorageRef:
        raise NotImplementedError

    def put_bytes(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> ObjectStorageRef:
        raise NotImplementedError

    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    def list_keys(self, suffix: str = "") -> list[str]:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError
