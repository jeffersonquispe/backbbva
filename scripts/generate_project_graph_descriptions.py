#!/usr/bin/env python3
"""Generate cached LLM descriptions for graph components not curated by hand.

The checked-in JSON cache keeps ordinary graph builds and CI deterministic;
run ``make project-graph-descriptions`` after frontend component changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.application.ports.llm_unit_of_work_port import (  # noqa: E402, I001
    LLMMessage,
    LLMMessageRole,
)
from scripts.build_project_graph import (  # noqa: E402, I001
    GENERATED_DESCRIPTIONS,
    build,
)


def _strip_json_fence(raw: str) -> str:
    value = raw.strip()
    marker = chr(96) * 3
    if value.startswith(marker) and value.endswith(marker):
        value = value[len(marker) : -len(marker)].strip()
        if value.startswith("json"):
            value = value[4:].strip()
    return value


def _components(frontend: Path) -> list[dict[str, str]]:
    graph, errors = build(frontend)
    if errors:
        raise ValueError("\n".join(errors))
    generated = {}
    if GENERATED_DESCRIPTIONS.is_file():
        generated = json.loads(
            GENERATED_DESCRIPTIONS.read_text(encoding="utf-8")
        ).get("descriptions", {})
    components = []
    for node_id, node in sorted(graph.nodes.items()):
        if node["kind"] != "component" or node["description"] or generated.get(node_id):
            continue
        source = frontend / "src" / node["attrs"].get("file", "")
        excerpt = source.read_text(encoding="utf-8")[:5_000] if source.is_file() else ""
        components.append(
            {"id": node_id, "name": node["name"], "file": node["attrs"].get("file", ""),
             "source": excerpt}
        )
    return components


def _generate_batch(components: list[dict[str, str]], *, model: str) -> dict[str, str]:
    from src.infrastructure.llm.langchain import get_llm_unit_of_work_factory
    from src.infrastructure.monitoring.opentelemetry import get_monitoring

    records = [
        {"id": item["id"], "name": item["name"], "file": item["file"],
         "source_excerpt": item["source"]}
        for item in components
    ]
    llm = get_llm_unit_of_work_factory().create(
        model=model,
        monitoring=get_monitoring(),
        operation_name="project_graph_component_descriptions",
        temperature=0,
        max_tokens=3_000,
    )
    result = llm.invoke(
        [
            LLMMessage(
                role=LLMMessageRole.SYSTEM,
                content=(
                    "Describe frontend components for an internal ARIA fraud platform. "
                    "Return only JSON {\"descriptions\": {component_id: description}}. "
                    "Write concise Spanish descriptions (one or two sentences), grounded "
                    "only in each component's name, file and source. Describe its user "
                    "purpose and main responsibility. Do not infer permissions, backend "
                    "behavior, or business rules that the source does not show."
                ),
            ),
            LLMMessage(
                role=LLMMessageRole.USER,
                content=json.dumps(records, ensure_ascii=False),
            ),
        ]
    )
    try:
        payload: Any = json.loads(_strip_json_fence(result.content))
    except (ValueError, TypeError) as error:
        raise ValueError("LLM returned invalid JSON for component descriptions") from error
    descriptions = payload.get("descriptions") if isinstance(payload, dict) else None
    if not isinstance(descriptions, dict):
        raise ValueError("LLM response must contain a descriptions object")
    expected = {item["id"] for item in components}
    if set(descriptions) != expected:
        raise ValueError("LLM response component ids do not match the requested batch")
    cleaned = {}
    for node_id, description in descriptions.items():
        if not isinstance(description, str):
            raise ValueError(f"LLM description is not text: {node_id}")
        value = re.sub(r"\s+", " ", description).strip()
        if not value or len(value) > 500:
            raise ValueError(f"LLM description has invalid length: {node_id}")
        cleaned[node_id] = value
    return cleaned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frontend", type=Path, required=True)
    args = parser.parse_args()
    try:
        components = _components(args.frontend)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    current = {}
    if GENERATED_DESCRIPTIONS.is_file():
        current = json.loads(
            GENERATED_DESCRIPTIONS.read_text(encoding="utf-8")
        ).get("descriptions", {})
    if not components:
        print(f"No missing component descriptions ({len(current)} cached)")
        return 0
    os.environ.setdefault("GENAI_ENVIRONMENT", "local")
    os.environ.setdefault("API_V0_STR", "/api/v0")
    from src.infrastructure.core.config import genai_config

    model = genai_config.REPORT_LLM_MODEL or genai_config.EXECUTOR_LLM_MODEL
    if not model:
        print("REPORT_LLM_MODEL or EXECUTOR_LLM_MODEL must be configured", file=sys.stderr)
        return 2
    try:
        for offset in range(0, len(components), 8):
            current.update(_generate_batch(components[offset : offset + 8], model=model))
            GENERATED_DESCRIPTIONS.write_text(
                json.dumps({"version": 1, "descriptions": current},
                           ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"Generated {len(current)} component descriptions in {GENERATED_DESCRIPTIONS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
