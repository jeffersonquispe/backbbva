from __future__ import annotations

from abc import ABC, abstractmethod


class EventSink(ABC):
    """Writes generated rows into an aria-api Dataset (POST
    /datasets/{name}/rows), creating it empty first if it doesn't exist yet.
    Crosses the event-simulator microservice's boundary - never touches
    aria-api's dataset storage (MinIO/DynamoDB) directly."""

    @abstractmethod
    def write_batch(self, dataset_name: str, rows: list[dict]) -> int:
        """Returns the dataset's new total row count."""
        ...
