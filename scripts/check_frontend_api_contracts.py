"""Compare every frontend API route/method with the backend OpenAPI surface."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("API_V0_STR", "/api/v0")
os.environ.setdefault("GENAI_ENVIRONMENT", "test")

from src.infrastructure.entrypoint.api.fastapi_app import create_app


def main() -> int:
    backend_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--frontend",
        type=Path,
        default=backend_root.parent / "frontend_mockup",
        help="Frontend checkout (Jenkins clones it inside the backend workspace).",
    )
    frontend_root = parser.parse_args().frontend.resolve()
    checker = frontend_root / "scripts" / "check-api-contracts.mjs"
    if not checker.is_file():
        raise SystemExit(f"Frontend contract checker not found: {checker}")

    openapi = create_app().openapi()
    with tempfile.TemporaryDirectory(prefix="aria-openapi-") as directory:
        spec_path = Path(directory) / "openapi.json"
        spec_path.write_text(json.dumps(openapi), encoding="utf-8")
        return subprocess.run(
            ["node", str(checker), str(spec_path)],
            cwd=frontend_root,
            check=False,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
