from src.infrastructure.persistence.database.dynamodb.repositories.agent_repositories import (
    _active_prompt,
    _named_item,
    _prompt,
)


def test_prompt_name_is_the_persisted_dynamodb_key() -> None:
    item = _named_item(
        {
            "name": "orchestrator.system",
            "version": 1,
            "content": "prompt body",
            "content_hash": "hash",
            "status": "ACTIVE",
            "created_at": "2026-10-18T00:00:00+00:00",
        }
    )

    assert item["prompt_name"] == "orchestrator.system"
    assert "name" not in item


def test_prompt_records_decode_from_prompt_name_key() -> None:
    prompt = _prompt(
        {
            "prompt_name": "orchestrator.system",
            "version": 1,
            "content": "prompt body",
            "content_hash": "hash",
            "status": "ACTIVE",
            "created_at": "2026-10-18T00:00:00+00:00",
        }
    )
    active = _active_prompt(
        {
            "prompt_name": "orchestrator.system",
            "version": 1,
            "activated_at": "2026-10-18T00:00:00+00:00",
            "activated_by": "system-seed",
        }
    )

    assert prompt.name == active.name == "orchestrator.system"
