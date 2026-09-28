from __future__ import annotations

import random
from abc import ABC, abstractmethod


class DatasetReaderGateway(ABC):
    """Reads one random row out of an existing aria-api Dataset (GET
    /datasets/{name}/rows) - backs GeneratorKind.SEED_RECREATION, which
    rewrites a real field value instead of inventing one from scratch.
    Crosses the event-simulator microservice's boundary - never touches
    aria-api's dataset storage directly."""

    @abstractmethod
    def sample_row(self, dataset_name: str, rng: random.Random) -> dict | None:
        """Returns None if the dataset is missing or has no rows."""
        ...
