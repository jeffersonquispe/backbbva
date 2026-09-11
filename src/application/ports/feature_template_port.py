from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass
class FeatureTemplate:
    id: str
    name: str
    description: str
    configuration: dict[str, Any]
    created_at: datetime


class FeatureTemplateRepository(Protocol):
    def create(self, template: FeatureTemplate) -> FeatureTemplate: ...
    def list(self) -> list[FeatureTemplate]: ...
    def delete(self, template_id: str) -> None: ...
