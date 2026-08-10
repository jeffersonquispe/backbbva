from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from src.application.ports.object_storage_port import ObjectStorageRef


@dataclass
class DocumentAnalystDecisionInput:
    alert_id: UUID
    workflow_execution_id: UUID
    # step_name -> that step's output data (pre_process, profiling,
    # classification, adversarial, analyst), already plain dicts.
    steps: dict[str, dict[str, Any]]


@dataclass
class DocumentAnalystDecisionOutput:
    report: str
    object_storage_ref: ObjectStorageRef
