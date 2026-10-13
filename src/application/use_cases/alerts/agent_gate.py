from __future__ import annotations

from src.application.ports.operational_settings_port import OperationalSettings
from src.domain.alerts.entities import (
    PROCESSED_WHILE_AGENT_OFF,
    AlertOrigin,
)


def agent_off_skip_reason(
    origin: AlertOrigin, settings: OperationalSettings
) -> str | None:
    """Why this alert must not be processed, or None to process it.

    With the agent switched off, manual runs and CSV batch runs still go
    through (someone is deliberately testing); simulator and production
    traffic is skipped. Checked by the worker when the workflow starts, so
    alerts queued before the switch was flipped are skipped too."""
    if settings.agent_enabled or origin in PROCESSED_WHILE_AGENT_OFF:
        return None
    return f"Agente apagado: las alertas de origen '{origin.value}' no se procesan."
