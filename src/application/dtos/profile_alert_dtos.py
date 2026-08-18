from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from src.application.dtos.pre_process_dtos import PreProcessAlertOutput


@dataclass
class ProfileAlertInput:
    alert_id: UUID
    pre_process: PreProcessAlertOutput


@dataclass
class ProfileAlertOutput:
    user_profile: str
    transaction_profile: str
    transactional_profile: str
    input_tokens: int = 0
    output_tokens: int = 0
