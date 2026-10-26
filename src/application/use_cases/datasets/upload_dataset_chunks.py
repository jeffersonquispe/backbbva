from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import PurePath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, TypedDict, cast
from uuid import UUID

from src.application.dtos.dataset_dtos import UploadDatasetInput, UploadDatasetOutput
from src.application.errors import NotFoundError, ValidationError
from src.application.ports.clock_port import Clock
from src.application.ports.dataset_port import DatasetRepository
from src.application.ports.id_generator_port import IdGenerator
from src.application.ports.object_storage_port import ObjectStoragePort
from src.application.runtime_defaults import DEFAULT_ID_GENERATOR, resolve_clock
from src.application.use_cases.datasets.upload_dataset import UploadDatasetUseCase
from src.domain.datasets.entities import DatasetAnalysisStatus

PART_SIZE_BYTES = 5 * 1024 * 1024
MAX_UPLOAD_PARTS = 10_000
UPLOAD_SESSION_TTL = timedelta(hours=24)
_UPLOAD_PREFIX = "__dataset_uploads__/"


@dataclass(frozen=True)
class DatasetUploadSessionOutput:
    upload_id: UUID
    name: str
    part_size_bytes: int
    total_parts: int
    expires_at: str


class DatasetUploadSessionNotFoundError(NotFoundError):
    pass


class _StoredUploadSession(TypedDict):
    upload_id: str
    name: str
    total_size_bytes: int
    part_size_bytes: int
    total_parts: int
    expires_at: str
    completed: dict[str, str | None] | None


class DatasetUploadChunksUseCase:
    """Stage bounded REST chunks in backend object storage, then upload CSV."""

    def __init__(
        self,
        storage: ObjectStoragePort,
        datasets: DatasetRepository,
        upload_dataset: UploadDatasetUseCase,
        *,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
    ) -> None:
        self._storage = storage
        self._datasets = datasets
        self._upload_dataset = upload_dataset
        self._clock = resolve_clock(clock)
        self._id_generator = id_generator or DEFAULT_ID_GENERATOR

    def start(self, filename: str, total_size_bytes: int) -> DatasetUploadSessionOutput:
        self._cleanup_expired_sessions()
        clean_filename = PurePath(filename).name
        if (
            not filename
            or clean_filename != filename
            or "/" in filename
            or "\\" in filename
            or not filename.casefold().endswith(".csv")
        ):
            raise ValidationError("A plain .csv filename is required")
        name = filename[:-4]
        if not name.strip() or len(name) > 180:
            raise ValidationError("Dataset filename must contain 1 to 180 characters")
        if total_size_bytes < 1:
            raise ValidationError("Dataset file must not be empty")
        total_parts = (total_size_bytes + PART_SIZE_BYTES - 1) // PART_SIZE_BYTES
        if total_parts > MAX_UPLOAD_PARTS:
            raise ValidationError("Dataset exceeds the maximum upload size")
        if any(record.name.casefold() == name.casefold() for record in self._datasets.list()):
            raise FileExistsError(f"Dataset '{name}' already exists")

        upload_id = self._new_id()
        expires_at = self._clock.now() + UPLOAD_SESSION_TTL
        session: _StoredUploadSession = {
            "upload_id": str(upload_id),
            "name": name,
            "total_size_bytes": total_size_bytes,
            "part_size_bytes": PART_SIZE_BYTES,
            "total_parts": total_parts,
            "expires_at": expires_at.isoformat(),
            "completed": None,
        }
        self._save_session(upload_id, session)
        return DatasetUploadSessionOutput(
            upload_id=upload_id,
            name=name,
            part_size_bytes=PART_SIZE_BYTES,
            total_parts=total_parts,
            expires_at=expires_at.isoformat(),
        )

    def upload_part(self, upload_id: UUID, part_number: int, content: bytes) -> None:
        session = self._load_open_session(upload_id)
        if not 1 <= part_number <= int(session["total_parts"]):
            raise ValidationError("Part number is outside this upload session")
        expected_size = self._expected_part_size(session, part_number)
        if len(content) != expected_size:
            raise ValidationError(
                f"Part {part_number} must contain exactly {expected_size} bytes"
            )
        self._storage.put_bytes(
            self._part_key(upload_id, part_number),
            content,
            content_type="application/octet-stream",
        )

    def complete(self, upload_id: UUID) -> UploadDatasetOutput:
        session = self._load_session(upload_id)
        completed = session.get("completed")
        if isinstance(completed, dict):
            return UploadDatasetOutput(
                name=str(completed["name"]),
                status=DatasetAnalysisStatus(str(completed["status"])),
                async_operation_id=(
                    UUID(completed["async_operation_id"])
                    if completed.get("async_operation_id")
                    else None
                ),
            )
        self._assert_not_expired(session)

        expected_size = int(session["total_size_bytes"])
        with SpooledTemporaryFile(max_size=PART_SIZE_BYTES * 2, mode="w+b") as assembled:
            total_size = 0
            for part_number in range(1, int(session["total_parts"]) + 1):
                key = self._part_key(upload_id, part_number)
                try:
                    actual_size = self._storage.get_size(key)
                except Exception as exc:  # adapter-specific missing object errors
                    raise ValidationError(f"Upload part {part_number} is missing") from exc
                if actual_size != self._expected_part_size(session, part_number):
                    raise ValidationError(f"Upload part {part_number} has an invalid size")
                with self._storage.get_stream(key) as part_stream:
                    shutil.copyfileobj(part_stream, assembled)
                total_size += actual_size

            if total_size != expected_size:
                raise ValidationError("Uploaded parts do not match the declared file size")
            assembled.seek(0)
            result = self._upload_dataset.execute(
                UploadDatasetInput(
                    name=session["name"], file=cast(BinaryIO, assembled)
                )
            )

        session["completed"] = {
            "name": result.name,
            "status": result.status.value,
            "async_operation_id": (
                str(result.async_operation_id) if result.async_operation_id else None
            ),
        }
        self._save_session(upload_id, session)
        self._delete_parts(upload_id)
        return result

    def abort(self, upload_id: UUID) -> None:
        self._load_session(upload_id)
        self._delete_session(upload_id)

    def _load_open_session(self, upload_id: UUID) -> _StoredUploadSession:
        session = self._load_session(upload_id)
        if session.get("completed") is not None:
            raise ValidationError("Upload session is already complete")
        self._assert_not_expired(session)
        return session

    def _load_session(self, upload_id: UUID) -> _StoredUploadSession:
        try:
            raw = self._storage.get_bytes(self._session_key(upload_id))
            session = json.loads(raw)
        except Exception as exc:  # adapter-specific missing object errors
            raise DatasetUploadSessionNotFoundError(
                f"Upload session not found: {upload_id}"
            ) from exc
        if not isinstance(session, dict) or session.get("upload_id") != str(upload_id):
            raise DatasetUploadSessionNotFoundError(
                f"Upload session not found: {upload_id}"
            )
        return cast(_StoredUploadSession, session)

    def _assert_not_expired(self, session: _StoredUploadSession) -> None:
        if datetime.fromisoformat(session["expires_at"]) <= self._clock.now():
            self._delete_session(UUID(session["upload_id"]))
            raise DatasetUploadSessionNotFoundError("Upload session has expired")

    def _expected_part_size(self, session: _StoredUploadSession, part_number: int) -> int:
        remaining = int(session["total_size_bytes"]) - (
            part_number - 1
        ) * int(session["part_size_bytes"])
        return min(int(session["part_size_bytes"]), remaining)

    def _save_session(self, upload_id: UUID, session: _StoredUploadSession) -> None:
        self._storage.put_text(
            self._session_key(upload_id),
            json.dumps(session, separators=(",", ":")),
            content_type="application/json",
        )

    def _delete_parts(self, upload_id: UUID) -> None:
        prefix = self._upload_prefix(upload_id) + "parts/"
        for item in self._storage.list_objects(prefix):
            self._storage.delete(item.key)

    def _delete_session(self, upload_id: UUID) -> None:
        prefix = self._upload_prefix(upload_id)
        for item in self._storage.list_objects(prefix):
            self._storage.delete(item.key)

    def _cleanup_expired_sessions(self) -> None:
        now = self._clock.now()
        for item in self._storage.list_objects(_UPLOAD_PREFIX):
            if not item.key.endswith("/session.json"):
                continue
            try:
                session = json.loads(self._storage.get_bytes(item.key))
                expired = datetime.fromisoformat(str(session["expires_at"])) <= now
                upload_id = UUID(str(session["upload_id"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                self._storage.delete(item.key)
                continue
            if expired:
                self._delete_session(upload_id)

    def _new_id(self) -> UUID:
        return self._id_generator.new_id()

    @staticmethod
    def _upload_prefix(upload_id: UUID) -> str:
        return f"{_UPLOAD_PREFIX}{upload_id}/"

    @classmethod
    def _session_key(cls, upload_id: UUID) -> str:
        return f"{cls._upload_prefix(upload_id)}session.json"

    @classmethod
    def _part_key(cls, upload_id: UUID, part_number: int) -> str:
        return f"{cls._upload_prefix(upload_id)}parts/{part_number:05d}.bin"
