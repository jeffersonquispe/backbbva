from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO


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

    def put_file(
        self,
        key: str,
        file: BinaryIO,
        content_type: str = "application/octet-stream",
    ) -> ObjectStorageRef:
        """Upload an already-open file without loading it into memory."""
        raise NotImplementedError

    def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    def get_stream(self, key: str) -> BinaryIO:
        """Return a readable object stream. The caller closes it."""
        raise NotImplementedError

    def get_size(self, key: str) -> int:
        raise NotImplementedError

    def list_keys(self, suffix: str = "") -> list[str]:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError
