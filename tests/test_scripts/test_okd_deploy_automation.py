import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "deploy/okd/automation/deploy.py"
SPEC = importlib.util.spec_from_file_location("okd_deploy", SCRIPT)
assert SPEC and SPEC.loader
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


class OkdDeployAutomationTests(unittest.TestCase):
    def test_only_project_images_are_registered_and_resolved_from_deployments(self):
        config = deploy.load_config()
        self.assertEqual(
            {"api", "event-api", "mcp", "worker", "training-worker", "simulator-worker", "frontend"},
            set(config["services"]),
        )
        self.assertTrue(all(service["current_image"].startswith(deploy.ARTIFACTORY)
                            for service in config["services"].values()))
        self.assertFalse(any("nginx" in service["current_image"] for service in config["services"].values()))
        self.assertEqual(
            "https://bbva.ghe.com/free/aria-agente-prevencion-fraude-frontend.git",
            config["repositories"]["frontend"]["url"],
        )
        self.assertEqual("frontend", config["services"]["frontend"]["repository"])

    def test_source_checkout_clones_and_refreshes_branch_without_touching_origin(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            root = Path(directory)
            origin = root / "origin"
            origin.mkdir()
            subprocess.run(["git", "init", "--quiet", "--initial-branch=main"], cwd=origin, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=origin, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=origin, check=True)
            (origin / "source.txt").write_text("first\n")
            subprocess.run(["git", "add", "source.txt"], cwd=origin, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "first"], cwd=origin, check=True)
            config = {"repositories": {"backend": {"url": origin.as_uri()}}}
            cache: dict[str, tuple[str, str] | None] = {}
            checkout = deploy.prepare_source("backend", "main", config, root / "stage", cache)
            self.assertEqual("first\n", (checkout / "source.txt").read_text())
            (origin / "source.txt").write_text("second\n")
            subprocess.run(["git", "add", "source.txt"], cwd=origin, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "second"], cwd=origin, check=True)
            refreshed = deploy.prepare_source("backend", "main", config, root / "stage", cache)
            self.assertEqual(checkout, refreshed)
            self.assertEqual("second\n", (refreshed / "source.txt").read_text())

    def test_custom_tag_validation_and_target_derivation(self):
        config = deploy.load_config()
        service = config["services"]["api"]
        self.assertTrue(deploy.image_target(service, "a" * 40, "release-42", config).endswith(":release-42"))
        with self.assertRaises(ValueError):
            deploy.image_target(service, "a" * 40, "bad tag", config)

    def test_staging_rejects_modified_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            artifact = stage / "image.tar"
            artifact.write_bytes(b"complete image")
            marker = {"service": "api", "target": "image:tag", "artifact": artifact.name,
                      "sha256": deploy.sha256(artifact), "status": "pending"}
            (stage / "image.json").write_text(json.dumps(marker))
            self.assertEqual("pending", deploy.load_artifacts(stage)[0]["status"])
            artifact.write_bytes(b"truncated")
            self.assertEqual("invalid", deploy.load_artifacts(stage)[0]["status"])

    def test_state_commit_is_written_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory)
            expected = {"published": {"api": {"commit": "abc"}}, "artifacts": {}}
            deploy.write_state(stage, expected)
            self.assertEqual(expected, deploy.read_state(stage))
            self.assertFalse((stage / "state.tmp").exists())

    def test_release_pipelines_cover_each_registered_service_and_keep_build_publish_separate(self):
        pipeline_file = SCRIPT.parent / "tekton/pipelines.release.yaml"
        documents = [json.loads(document) for document in pipeline_file.read_text().split("---")
                     if document.strip()]
        self.assertEqual({"aria-build-images-v1", "aria-publish-images-v1"},
                         {document["metadata"]["name"] for document in documents})
        build, publish = documents
        build_params = {param["name"] for param in build["spec"]["params"]}
        self.assertTrue({"github-user", "github-token"}.issubset(build_params))
        self.assertNotIn("github-token", {param["name"] for param in publish["spec"].get("params", [])})
        services = set(deploy.load_config()["services"])
        build_tasks = {task["name"][len("build-"):] for task in build["spec"]["tasks"]
                       if task["name"].startswith("build-")}
        publish_tasks = {task["name"][len("publish-"):] for task in publish["spec"]["tasks"]
                         if task["name"].startswith("publish-")}
        self.assertEqual(services, build_tasks)
        self.assertEqual(services, publish_tasks)
        self.assertTrue(all(task["taskRef"]["name"] == "aria-build-staged-image-v2"
                            for task in build["spec"]["tasks"] if task["name"].startswith("build-")))
        self.assertTrue(all(task["taskRef"]["name"] == "aria-publish-pending-image-v2"
                            for task in publish["spec"]["tasks"]))
        build_tasks = [task for task in build["spec"]["tasks"] if task["name"].startswith("build-")]
        self.assertTrue(all("when" not in task for task in build_tasks))
        self.assertTrue(all(any(param["name"] == "should-build" for param in task["params"])
                            for task in build_tasks))

    def test_release_pipeline_run_has_timeout_margin_and_no_token_value(self):
        template = SCRIPT.parent / "tekton/pipelineruns.release.yaml.tmpl"
        content = template.read_text()
        self.assertEqual(2, content.count("pipeline: 50m"))
        self.assertNotIn("name: github-token", content.lower())
        self.assertIn("secretName: artifactory-auth", content)

    def test_change_detection_uses_declared_tekton_result_paths(self):
        task_file = SCRIPT.parent / "tekton/tasks.release.yaml"
        content = task_file.read_text()
        self.assertNotIn("$(results.' + result", content)
        for service in deploy.load_config()["services"]:
            self.assertIn(f"value: $(results.build-{service}.path)", content)

    def test_release_tasks_are_available_as_individual_manifests(self):
        task_dir = SCRIPT.parent / "tekton/tasks"
        task_files = sorted(task_dir.glob("*.yaml"))
        self.assertEqual(5, len(task_files))
        for task_file in task_files:
            self.assertEqual(1, task_file.read_text().count("apiVersion: tekton.dev/v1"))

    def test_okd_build_task_uses_unprivileged_kaniko_and_stages_without_pushing(self):
        build = (SCRIPT.parent / "tekton/tasks/build-staged-image.yaml").read_text()
        self.assertIn("ghcr.io/osscontainertools/kaniko:v1.28.5-debug", build)
        self.assertIn("--no-push --no-push-cache", build)
        self.assertIn("--secret=\"id=artifactory_user", build)
        self.assertIn("--tar-path=", build)
        self.assertNotIn("buildah bud", build)
        publish = (SCRIPT.parent / "tekton/tasks/publish-pending-image.yaml").read_text()
        self.assertIn("docker-archive:$artifact", publish)


if __name__ == "__main__":
    unittest.main()
