from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.application.ports.model_scoring_port import ModelScoringPort
from src.infrastructure.core.config import genai_config


class MCPModelScoringClient(ModelScoringPort):
    """Small stdlib HTTP client; keeps ML runtime out of the alert worker."""

    def score_alert(self, alert_id: str, model_id: str | None = None) -> dict:
        body = json.dumps({"alert_id": alert_id, "model_id": model_id}).encode()
        request = Request(
            f"{genai_config.MCP_BASE_URL.rstrip('/')}/internal/score",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=genai_config.MCP_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            try:
                return json.loads(exc.read())
            except (json.JSONDecodeError, OSError):
                raise RuntimeError(f"MCP scoring returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("MCP scoring service is unavailable") from exc
        if not isinstance(result, dict):
            raise RuntimeError("MCP scoring returned an invalid response")
        return result
