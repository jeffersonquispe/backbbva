#!/usr/bin/env python3
"""Build the multi-document Task bundle from the console-friendly Task files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = (
    ROOT / "tasks/clone-ghe-sources.yaml",
    ROOT / "tasks/detect-ghe-changes.yaml",
    ROOT / "tasks/build-staged-image.yaml",
    ROOT / "tasks/publish-pending-image.yaml",
    ROOT / "tasks/prepare-deployment-manifests.yaml",
)
OUTPUT = ROOT / "tasks.release.yaml"


def main() -> None:
    documents = [path.read_text().strip() for path in TASKS]
    OUTPUT.write_text("---\n" + "\n---\n".join(documents) + "\n")
    print(OUTPUT)


if __name__ == "__main__":
    main()
