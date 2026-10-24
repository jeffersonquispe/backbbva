import json
from uuid import UUID

from src.infrastructure.model_serving import mcp_scoring_client as client_module
from src.infrastructure.model_serving.mcp_scoring_client import (
    MCPModelScoringClient,
)


class InMemoryHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self._payload


def test_client_posts_alert_and_selected_model_to_mcp(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return InMemoryHTTPResponse({"score": 0.9, "model_id": "model-1"})

    monkeypatch.setattr(client_module, "urlopen", open_request)
    monkeypatch.setattr(client_module.genai_config, "MCP_BASE_URL", "http://mcp:8100")
    monkeypatch.setattr(client_module.genai_config, "MCP_TIMEOUT_SECONDS", 4.0)

    result = MCPModelScoringClient().score_alert(
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    )

    assert captured == {
        "url": "http://mcp:8100/internal/score",
        "body": {
            "alert_id": "00000000-0000-0000-0000-000000000001",
            "model_id": "00000000-0000-0000-0000-000000000002",
        },
        "timeout": 4.0,
    }
    assert result["score"] == 0.9


def test_client_posts_contract_row_and_model_to_mcp(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return InMemoryHTTPResponse(
            {"score": 0.42, "model_id": "model-2", "model_tag": "fraud-v1"}
        )

    monkeypatch.setattr(client_module, "urlopen", open_request)
    monkeypatch.setattr(client_module.genai_config, "MCP_BASE_URL", "http://mcp:8100")
    monkeypatch.setattr(client_module.genai_config, "MCP_TIMEOUT_SECONDS", 4.0)

    row = {"amount_value": 125.0, "eventtype": "payment"}
    result = MCPModelScoringClient().score_row(
        "00000000-0000-0000-0000-000000000002", row
    )

    assert captured == {
        "url": "http://mcp:8100/internal/score-row",
        "body": {
            "model_id": "00000000-0000-0000-0000-000000000002",
            "row": row,
        },
        "timeout": 4.0,
    }
    assert result["score"] == 0.42


def test_client_posts_exact_artifact_pin_for_optimizer_row(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return InMemoryHTTPResponse(
            {"score": 0.9, "model_id": "model-2", "artifact_sha256": "a" * 64}
        )

    monkeypatch.setattr(client_module, "urlopen", open_request)
    monkeypatch.setattr(client_module.genai_config, "MCP_BASE_URL", "http://mcp:8100")
    monkeypatch.setattr(client_module.genai_config, "MCP_TIMEOUT_SECONDS", 4.0)
    row = {"amount_value": 125.0}

    result = MCPModelScoringClient().score_pinned_row(
        "00000000-0000-0000-0000-000000000002", "a" * 64, row
    )

    assert captured == {
        "url": "http://mcp:8100/internal/score-pinned-row",
        "body": {
            "model_id": "00000000-0000-0000-0000-000000000002",
            "artifact_sha256": "a" * 64,
            "row": row,
        },
        "timeout": 4.0,
    }
    assert result["artifact_sha256"] == "a" * 64


def test_client_reloads_the_model_activated_in_repository(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def open_request(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return InMemoryHTTPResponse(
            {"loaded": True, "model_id": "00000000-0000-0000-0000-000000000003"}
        )

    monkeypatch.setattr(client_module, "urlopen", open_request)
    monkeypatch.setattr(client_module.genai_config, "MCP_BASE_URL", "http://mcp:8100")
    monkeypatch.setattr(client_module.genai_config, "MCP_TIMEOUT_SECONDS", 4.0)

    result = MCPModelScoringClient().reload_active_model()

    assert captured == {
        "url": "http://mcp:8100/internal/reload-active-model",
        "method": "POST",
        "timeout": 4.0,
    }
    assert result["model_id"] == "00000000-0000-0000-0000-000000000003"


class RecordingCeleryApp:
    def __init__(self) -> None:
        self.call = None

    def send_task(self, name, *, args, queue):
        self.call = (name, args, queue)


def test_model_training_dispatcher_uses_dedicated_queue(monkeypatch) -> None:
    from src.infrastructure.queues.celery import model_training_dispatcher

    app = RecordingCeleryApp()
    monkeypatch.setattr(model_training_dispatcher, "app", app)
    model_id = UUID("00000000-0000-0000-0000-000000000001")
    operation_id = UUID("00000000-0000-0000-0000-000000000002")

    model_training_dispatcher.CeleryModelTrainingDispatcher().dispatch(
        model_id, operation_id
    )

    assert app.call == (
        "models.train",
        [str(model_id), str(operation_id)],
        "model-training",
    )
