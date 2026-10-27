"""Upgrade known default agent context prompts; dry-run unless --apply."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from boto3.dynamodb.conditions import Key

from src.infrastructure.agents.context_prompt_upgrade import upgrade_context_prompts
from src.infrastructure.agents.factories import get_agent_prompt_repository
from src.infrastructure.persistence.database.dynamodb.client import (
    get_dynamodb_resource,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    table = get_dynamodb_resource().Table("agent_prompts")

    def latest_version(name: str) -> int:
        result = table.query(
            KeyConditionExpression=Key("prompt_name").eq(name),
            ScanIndexForward=False,
            ConsistentRead=True,
            Limit=1,
        )
        return int(result["Items"][0]["version"]) if result.get("Items") else 0

    results = upgrade_context_prompts(
        get_agent_prompt_repository(), latest_version, apply=args.apply
    )
    print(json.dumps([asdict(result) for result in results], indent=2))
    return int(
        any(
            result.outcome
            in {"custom_prompt", "invalid_hash", "missing_active", "missing_version"}
            for result in results
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
