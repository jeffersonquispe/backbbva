#!/usr/bin/env python3
"""Render release Pipelines from the service/Deployment registry."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CONFIG = ROOT / "deploy/okd/automation/services.json"
OUTPUT = ROOT / "deploy/okd/automation/tekton/pipelines.release.yaml"
BUILD_OUTPUT = ROOT / "deploy/okd/automation/tekton/pipeline-build.release.yaml"
PUBLISH_OUTPUT = ROOT / "deploy/okd/automation/tekton/pipeline-publish.release.yaml"
NAMESPACE = "aria-genai-dev"


def dump_doc(value: dict) -> str:
    # JSON is a YAML 1.2 subset and avoids adding a PyYAML runtime dependency.
    return json.dumps(value, indent=2, sort_keys=False)


def pipeline_metadata(name: str) -> dict:
    return {"apiVersion": "tekton.dev/v1", "kind": "Pipeline",
            "metadata": {"name": name, "namespace": NAMESPACE}}


def main() -> None:
    config = json.loads(CONFIG.read_text())
    if config.get("target_platform") != "linux/amd64":
        raise SystemExit("release build Task is pinned to AMD64; services.json target_platform must be linux/amd64")
    services = config["services"]
    build = pipeline_metadata("aria-build-images-v1")
    build["spec"] = {
        "params": [
        {"name": "mode", "type": "string", "default": "changed",
             "description": "changed, all o services"},
            {"name": "services", "type": "string", "default": "",
             "description": "Servicios separados por coma para mode=services"},
            {"name": "image-tag", "type": "string", "default": "",
             "description": "Tag común opcional; vacío usa el SHA de cada repo"},
            {"name": "backend-branch", "type": "string",
             "default": config["repositories"]["backend"]["default_branch"]},
            {"name": "frontend-branch", "type": "string",
             "default": config["repositories"]["frontend"]["default_branch"]},
            {"name": "github-user", "type": "string", "default": "",
             "description": "Usuario de GitHub Enterprise"},
            {"name": "github-token", "type": "string", "default": "",
             "description": "GitHub classic token; Tekton lo guarda en PipelineRun/TaskRun"},
        ],
        "workspaces": [{"name": "staging"}, {"name": "registry-auth"}],
        "tasks": []
    }
    build["spec"]["tasks"].append({
        "name": "clone-sources", "timeout": "10m",
        "taskRef": {"name": "aria-clone-ghe-sources-v1"},
        "params": [
            {"name": "backend-branch", "value": "$(params.backend-branch)"},
            {"name": "frontend-branch", "value": "$(params.frontend-branch)"},
            {"name": "github-user", "value": "$(params.github-user)"},
            {"name": "github-token", "value": "$(params.github-token)"},
        ],
        "workspaces": [{"name": "staging", "workspace": "staging"}],
    })
    build["spec"]["tasks"].append({
        "name": "detect-changes", "runAfter": ["clone-sources"], "timeout": "5m",
        "taskRef": {"name": "aria-detect-ghe-changes-v1"},
        "params": [
            {"name": "mode", "value": "$(params.mode)"},
            {"name": "services", "value": "$(params.services)"},
            {"name": "run-dir", "value": "$(tasks.clone-sources.results.run-dir)"},
            {"name": "backend-commit", "value": "$(tasks.clone-sources.results.backend-commit)"},
            {"name": "frontend-commit", "value": "$(tasks.clone-sources.results.frontend-commit)"},
        ],
        "workspaces": [{"name": "staging", "workspace": "staging"}],
    })
    image_repositories = {}
    for name, service in services.items():
        deployment = (ROOT / service["deployment"]).read_text()
        match = re.search(r"(?m)^\s+image:\s*([^\s#]+)",
                          deployment[deployment.index("- name: " + service["container"]):])
        if not match:
            raise SystemExit(f"cannot find deployed image for {name}")
        current_image = match.group(1)
        image_repositories[name] = current_image.rsplit(":", 1)[0]

    names = list(services)
    waves = [names[index:index + 3] for index in range(0, len(names), 3)]
    previous_wave: list[str] = []
    for wave_index, wave in enumerate(waves):
        current_wave: list[str] = []
        for name in wave:
            service = services[name]
            task_name = "build-" + name
            repo_name = service["repository"]
            context = "backend" if repo_name == "backend" else "frontend"
            source_commit = "$(tasks.clone-sources.results." + repo_name + "-commit)"
            dockerfile = service["dockerfile"]
            task = {
                "name": task_name,
                "runAfter": ["detect-changes"] + previous_wave,
                "timeout": "40m",
                "taskRef": {"name": "aria-build-staged-image-v2"},
                "params": [
                    {"name": "service", "value": name},
                    {"name": "should-build",
                     "value": "$(tasks.detect-changes.results.build-" + name + ")"},
                    {"name": "image-repository", "value": image_repositories[name]},
                    {"name": "image-tag", "value": "$(params.image-tag)"},
                    {"name": "source-commit", "value": source_commit},
                    {"name": "source-dir", "value": "$(tasks.clone-sources.results.run-dir)"},
                    {"name": "dockerfile", "value": "backend/" + dockerfile},
                    {"name": "context-dir", "value": context},
                    {"name": "source-branch", "value": "$(params." + repo_name + "-branch)"},
                    {"name": "target-platform", "value": config["target_platform"]},
                ],
                "workspaces": [
                    {"name": "staging", "workspace": "staging"},
                    {"name": "registry-auth", "workspace": "registry-auth"},
                ],
            }
            build["spec"]["tasks"].append(task)
            current_wave.append(task_name)
        previous_wave = current_wave

    publish = pipeline_metadata("aria-publish-images-v1")
    publish["spec"] = {"workspaces": [{"name": "staging"}, {"name": "registry-auth"}], "tasks": []}
    previous = []
    for name in names:
        task_name = "publish-" + name
        publish["spec"]["tasks"].append({
            "name": task_name, "runAfter": previous, "timeout": "8m",
            "taskRef": {"name": "aria-publish-pending-image-v2"},
            "params": [{"name": "service", "value": name}],
            "workspaces": [
                {"name": "staging", "workspace": "staging"},
                {"name": "registry-auth", "workspace": "registry-auth"},
            ],
        })
        previous = [task_name]
    publish["spec"]["finally"] = [{
        "name": "prepare-manifest-patch",
        "timeout": "3m",
        "taskRef": {"name": "aria-prepare-deployment-manifests-v1"},
        "workspaces": [{"name": "staging", "workspace": "staging"}],
    }]
    build_doc = dump_doc(build) + "\n"
    publish_doc = dump_doc(publish) + "\n"
    BUILD_OUTPUT.write_text(build_doc)
    PUBLISH_OUTPUT.write_text(publish_doc)
    OUTPUT.write_text("---\n" + build_doc + "---\n" + publish_doc)
    print(OUTPUT)


if __name__ == "__main__":
    main()
