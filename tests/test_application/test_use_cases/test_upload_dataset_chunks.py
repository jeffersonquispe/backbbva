from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID

import pytest

from src.application.dtos.dataset_dtos import UploadDatasetOutput
from src.application.errors import ValidationError
from src.application.ports.clock_port import Clock
from src.application.ports.object_storage_port import (
    ObjectInfo,
    ObjectStoragePort,
    ObjectStorageRef,
)
from src.application.use_cases.datasets.upload_dataset_chunks import (
    PART_SIZE_BYTES,
    DatasetUploadChunksUseCase,
    DatasetUploadSessionNotFoundError,
)
from src.domain.datasets.entities import DatasetAnalysisStatus


class InMemoryObjectStorage(ObjectStoragePort):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_text(self, key: str, content: str, content_type: str = "text/plain") -> ObjectStorageRef:
        return self.put_bytes(key, content.encode(), content_type)

    def put_bytes(
        self, key: str, content: bytes, content_type: str = "application/octet-stream"
    ) -> ObjectStorageRef:
        self.objects[key] = content
        return ObjectStorageRef("memory", key, f"memory://{key}")

    def put_file(
        self, key: str, file: BytesIO, content_type: str = "application/octet-stream"
    ) -> ObjectStorageRef:
        return self.put_bytes(key, file.read(), content_type)

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def get_stream(self, key: str) -> BytesIO:
        return BytesIO(self.objects[key])

    def get_size(self, key: str) -> int:
        return len(self.objects[key])

    def list_keys(self, suffix: str = "") -> list[str]:
        return [key for key in self.objects if key.endswith(suffix)]

    def list_objects(self, prefix: str = "") -> list[ObjectInfo]:
        return [
            ObjectInfo(key, len(content), datetime.now(UTC))
            for key, content in self.objects.items()
            if key.startswith(prefix)
        ]

    def delete(self, key: str) -> None:
        del self.objects[key]


class EmptyDatasetRepository:
    def list(self):
        return []


class RecordingUploadDatasetUseCase:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes]] = []

    def execute(self, input):
        self.uploads.append((input.name, input.file.read()))
        return UploadDatasetOutput(
            name=input.name,
            status=DatasetAnalysisStatus.PENDING,
            async_operation_id=UUID("00000000-0000-0000-0000-000000000001"),
        )


class FrozenClock(Clock):
    def __init__(self, now: datetime) -> None:
        self.value = now

    def now(self) -> datetime:
        return self.value


def _use_case(clock: Clock | None = None):
    storage = InMemoryObjectStorage()
    upload = RecordingUploadDatasetUseCase()
    use_case = DatasetUploadChunksUseCase(
        storage,
        EmptyDatasetRepository(),  # type: ignore[arg-type]
        upload,  # type: ignore[arg-type]
        clock=clock,
    )
    return use_case, storage, upload


def test_chunk_upload_reassembles_csv_and_complete_is_idempotent() -> None:
    use_case, storage, upload = _use_case()
    payload = b"x" * PART_SIZE_BYTES + b"last-bytes"
    session = use_case.start("sample.csv", len(payload))

    use_case.upload_part(session.upload_id, 1, payload[:PART_SIZE_BYTES])
    use_case.upload_part(session.upload_id, 2, payload[PART_SIZE_BYTES:])
    completed = use_case.complete(session.upload_id)
    repeated = use_case.complete(session.upload_id)

    assert completed == repeated
    assert completed.name == "sample"
    assert upload.uploads == [("sample", payload)]
    assert not any("/parts/" in key for key in storage.objects)


def test_chunk_upload_rejects_wrong_part_size_and_missing_parts() -> None:
    use_case, _, _ = _use_case()
    session = use_case.start("sample.csv", PART_SIZE_BYTES + 1)

    with pytest.raises(ValidationError, match="exactly"):
        use_case.upload_part(session.upload_id, 1, b"short")
    use_case.upload_part(session.upload_id, 1, b"x" * PART_SIZE_BYTES)
    with pytest.raises(ValidationError, match="part 2 is missing"):
        use_case.complete(session.upload_id)


def test_chunk_upload_rejects_bad_names_and_expires_sessions() -> None:
    now = datetime(2026, 10, 25, tzinfo=UTC)
    clock = FrozenClock(now)
    use_case, storage, _ = _use_case(clock)
    with pytest.raises(ValidationError, match="filename"):
        use_case.start("../sample.csv", 1)

    session = use_case.start("sample.csv", 1)
    clock.value += timedelta(hours=24, seconds=1)
    with pytest.raises(DatasetUploadSessionNotFoundError, match="expired"):
        use_case.upload_part(session.upload_id, 1, b"x")
    assert not any(session.upload_id.hex in key.replace("-", "") for key in storage.objects)


def test_chunk_upload_abort_removes_manifest_and_parts() -> None:
    use_case, storage, _ = _use_case()
    session = use_case.start("sample.csv", 1)
    use_case.upload_part(session.upload_id, 1, b"x")

    use_case.abort(session.upload_id)

    assert not any(str(session.upload_id) in key for key in storage.objects)
