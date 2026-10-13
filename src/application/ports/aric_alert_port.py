from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class AricAlertSignals:
    is_mobile_rat: bool | None = None
    is_emulator_rat: bool | None = None
    is_rat: bool | None = None
    is_bot: bool | None = None
    ind_robo1: bool | None = None
    is_on_call_active: bool | None = None
    is_voip_on_call: bool | None = None
    screen_broadcast: bool | None = None


class AricAlertPort(ABC):
    def fetch_signals(
        self,
        event_id: str,
        session_id: str | None,
    ) -> AricAlertSignals:
        raise NotImplementedError
