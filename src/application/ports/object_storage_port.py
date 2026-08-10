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
