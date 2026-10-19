from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.configurations.entities import TagCategory


@dataclass
class TagEntry:
    id: str
    category: TagCategory
    value: str
    created_at: datetime
    updated_at: datetime
    active: bool = True
