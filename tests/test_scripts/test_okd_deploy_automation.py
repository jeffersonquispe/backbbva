import base64
import contextlib
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "deploy/okd/automation/deploy.py"
SPEC = importlib.util.spec_from_file_location("okd_deploy", SCRIPT)
assert SPEC and SPEC.loader
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


@contextlib.contextmanager
def replaced(target, **attributes):
    """Temporarily replace attributes of ``target`` (hand-written, no unittest.mock)."""
    missing = object()
    saved = {name: getattr(target, name, missing) for name in attributes}
    for name, value in attributes.items():
        setattr(target, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is missing:
                delattr(target, name)
            else:
                setattr(target, name, value)


@contextlib.contextmanager
def environment(values, remove=()):
    saved = dict(os.environ)
    os.environ.update(values)
    for name in remove:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


class Recorder:
    """Callable that records its calls and returns a fixed value."""

    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class OkdDeployAutomationTests(unittest.TestCase):
    def test_local_repository_checkout_accepts_only_clean_expected_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory) / "frontend"
            checkout.mkdir()
            subprocess.run(["git", "init", "-b", "feature/test"], cwd=checkout,
                           check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=checkout, check=True)
            (checkout / "README.md").write_text("committed\n")
            subprocess.run(["git", "add", "README.md"], cwd=checkout, check=True)
            subprocess.run(["git", "commit", "-m", "test"], cwd=checkout, check=True,
                           capture_output=True)
            config = {"repositories": {"frontend": {"local_checkout": str(checkout)}}}
            self.assertEqual(checkout.resolve(),
                             deploy.local_repository_checkout("frontend", config, "feature/test"))
            (checkout / "README.md").write_text("dirty\n")
            with self.assertRaisesRegex(RuntimeError, "tiene cambios"):
                deploy.local_repository_checkout("frontend", config, "feature/test")
            with self.assertRaisesRegex(RuntimeError, "se esperaba"):
                deploy.local_repository_checkout("frontend", config, "main")

    def test_registry_credentials_can_be_read_from_explicit_docker_auth_file(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory) / "auth.json"
            encoded = base64.b64encode(b"test-user:test-token").decode()
            auth_path.write_text(json.dumps({"auths": {
                f"https://{deploy.ARTIFACTORY}/": {"auth": encoded}
            }}))
            self.assertEqual(("test-user", "test-token"),
                             deploy.existing_registry_credentials(auth_path))

    def test_registry_credentials_can_be_read_from_root_key_auth_file(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory) / "auth.json"
            encoded = base64.b64encode(b"test-user:test-token").decode()
            auth_path.write_text(json.dumps({deploy.ARTIFACTORY: {
                "username": "test-user", "email": "test@example.invalid", "auth": encoded
            }}))
            self.assertEqual(("test-user", "test-token"),
                             deploy.existing_registry_credentials(auth_path))

    def test_explicit_auth_file_without_artifactory_entry_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            auth_path = Path(directory) / "auth.json"
            auth_path.write_text('{"auths": {"registry.example.invalid": {}}}')
            with self.assertRaisesRegex(ValueError, "no contiene credenciales"):
                deploy.existing_registry_credentials(auth_path)

    def test_registry_login_error_includes_diagnostic_but_redacts_credentials(self):
        failed = subprocess.CompletedProcess(
            args=["podman", "login"], returncode=1, stdout="",
            stderr="login failed for test-user with password test-token",
        )
        with environment({"ARTIFACTORY_USER": "test-user", "ARTIFACTORY_PASSWORD": "test-token"}), \
                replaced(deploy, existing_registry_credentials=lambda *a, **k: None,
                         run=lambda *a, **k: failed):
            with self.assertRaises(RuntimeError) as raised:
                deploy.build_auth("podman")
        message = str(raised.exception)
        self.assertIn("login failed", message)
        self.assertNotIn("test-user", message)
        self.assertNotIn("test-token", message)

    def test_skip_auth_reuses_podman_auth_without_performing_login(self):
        run_command = Recorder()
        with replaced(deploy, existing_registry_credentials=lambda *a, **k: ("test-user", "test-token"),
                      run=run_command):
            temp, auth_path = deploy.build_auth("podman", skip_login=True)
            try:
                self.assertEqual(Path.home() / ".config/containers/auth.json", auth_path)
                self.assertEqual("test-user", (Path(temp.name) / "artifactory_user").read_text())
                self.assertEqual("test-token", (Path(temp.name) / "artifactory_password").read_text())
                self.assertEqual([], run_command.calls)
            finally:
                temp.cleanup()

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
            stale_secret = checkout / "podman-build-secret12345"
            stale_secret.write_text("temporary secret")
            (origin / "source.txt").write_text("second\n")
            subprocess.run(["git", "add", "source.txt"], cwd=origin, check=True)
            subprocess.run(["git", "commit", "--quiet", "-m", "second"], cwd=origin, check=True)
            refreshed = deploy.prepare_source("backend", "main", config, root / "stage", cache)
            self.assertEqual(checkout, refreshed)
            self.assertEqual("second\n", (refreshed / "source.txt").read_text())
            self.assertFalse(stale_secret.exists())

    def test_podman_secret_cleanup_only_removes_generated_secret_filenames(self):
        with tempfile.TemporaryDirectory() as directory:
            context = Path(directory)
            generated = context / "podman-build-secret123"
            unrelated = context / "podman-build-secret-not-generated"
            generated.write_text("secret")
            unrelated.write_text("leave this file")
            deploy.cleanup_podman_build_secrets(context)
            self.assertFalse(generated.exists())
            self.assertTrue(unrelated.exists())

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

    def test_publish_rejects_non_amd64_or_legacy_artifact_before_registry_access(self):
        with self.assertRaisesRegex(RuntimeError, "destino requiere linux/amd64"):
            deploy.publish_one({"service": "frontend", "status": "pending", "platform": "linux/arm64"},
                               None, 3, "linux/amd64")

    def test_publish_selection_skips_legacy_platform_and_keeps_verified_pending_images(self):
        items = [
            {"service": "api", "status": "pending", "platform": "linux/amd64"},
            {"service": "frontend", "status": "pending"},
            {"service": "worker", "status": "published", "platform": "linux/amd64"},
        ]
        selected = deploy.pending_artifacts_for_platform(items, "linux/amd64")
        self.assertEqual(["api"], [item["service"] for item in selected])

    def test_publish_can_retarget_only_selected_staged_service_without_rebuilding(self):
        items = [
            {"service": "frontend", "status": "pending", "platform": "linux/amd64",
             "source_commit": "a" * 40, "target": "registry.example/frontend:" + "a" * 40},
            {"service": "api", "status": "pending", "platform": "linux/amd64",
             "source_commit": "b" * 40, "target": "registry.example/api:" + "b" * 40},
        ]
        config = {"services": {
            "frontend": {"current_image": "registry.example/frontend:old"},
            "api": {"current_image": "registry.example/api:old"},
        }}
        selected = deploy.prepare_pending_publications(
            items, "linux/amd64", config, "frontend", "frontend-rebuild-2"
        )
        self.assertEqual(["frontend"], [item["service"] for item in selected])
        self.assertEqual("registry.example/frontend:frontend-rebuild-2", selected[0]["target"])
        self.assertEqual("registry.example/api:" + "b" * 40, items[1]["target"])

    def test_publish_requires_explicit_service_selection_for_custom_tag(self):
        config = {"services": {"frontend": {"current_image": "registry.example/frontend:old"}}}
        with self.assertRaisesRegex(ValueError, "indique --services explícitamente"):
            deploy.prepare_pending_publications([], "linux/amd64", config, None, "frontend-rebuild-2")

    def test_publish_defaults_to_current_staged_artifact_and_leaves_history_untouched(self):
        items = [
            {"service": "frontend", "artifact": "old.oci.tar", "status": "pending",
             "platform": "linux/amd64", "target": "registry.example/frontend:old"},
            {"service": "frontend", "artifact": "current.oci.tar", "status": "pending",
             "platform": "linux/amd64", "target": "registry.example/frontend:current"},
        ]
        config = {"services": {"frontend": {"current_image": "registry.example/frontend:base"}}}
        selected = deploy.prepare_pending_publications(
            items, "linux/amd64", config, "frontend", latest_artifacts={"frontend": "current.oci.tar"}
        )
        self.assertEqual(["current.oci.tar"], [item["artifact"] for item in selected])
        history = deploy.prepare_pending_publications(
            items, "linux/amd64", config, "frontend", latest_artifacts={"frontend": "current.oci.tar"},
            include_history=True,
        )
        self.assertEqual(["old.oci.tar", "current.oci.tar"], [item["artifact"] for item in history])

    def test_oci_archive_details_reads_manifest_and_platform_without_extracting(self):
        import hashlib
        import io
        import tarfile

        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "image.oci.tar"
            config_bytes = json.dumps({"os": "linux", "architecture": "amd64",
                                       "rootfs": {"diff_ids": ["sha256:layer"]}}).encode()
            config_hash = hashlib.sha256(config_bytes).hexdigest()
            manifest_bytes = json.dumps({
                "schemaVersion": 2,
                "config": {"digest": f"sha256:{config_hash}"},
                "layers": [{"digest": "sha256:compressed-layer", "size": 10}],
            }).encode()
            manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
            index_bytes = json.dumps({"schemaVersion": 2, "manifests": [{
                "digest": f"sha256:{manifest_hash}",
                "annotations": {"org.opencontainers.image.ref.name": "localhost/example:test"},
            }]}).encode()
            with tarfile.open(archive, "w") as output:
                for name, content in (
                    ("index.json", index_bytes),
                    (f"blobs/sha256/{manifest_hash}", manifest_bytes),
                    (f"blobs/sha256/{config_hash}", config_bytes),
                ):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    output.addfile(info, io.BytesIO(content))
            self.assertEqual((manifest_bytes, "linux/amd64", "localhost/example:test"),
                             deploy.oci_archive_details(archive))

    def test_publisher_uses_podman_fallback_when_skopeo_is_missing(self):
        item = {"service": "api", "status": "pending", "platform": "linux/amd64",
                "_artifact_path": Path("image.oci.tar"), "target": "example/image:tag"}
        def which(name):
            return None if name == "skopeo" else "/usr/bin/podman"

        fallback = Recorder(item)
        with replaced(deploy.shutil, which=which), \
                replaced(deploy, oci_archive_details=lambda *a, **k: (b"manifest", "linux/amd64", "localhost/api:test"),
                         publish_one_with_podman=fallback):
            self.assertIs(item, deploy.publish_one(item, None, 3, "linux/amd64"))
            self.assertEqual([((item, None, 3, "linux/amd64", b"manifest", "localhost/api:test"), {})],
                             fallback.calls)

    def test_registry_tls_uses_explicit_corporate_ca_bundle_without_disabling_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "corporate-ca.pem"
            bundle.write_text("test CA bundle")
            load_locations = Recorder()

            class RecordingSslContext:
                load_verify_locations = load_locations

            context = RecordingSslContext()
            create_context = Recorder(context)
            with environment({"ARTIFACTORY_CA_BUNDLE": str(bundle)}), \
                    replaced(deploy.ssl, create_default_context=create_context):
                self.assertIs(context, deploy.registry_ssl_context())
            self.assertEqual([((), {})], create_context.calls)
            self.assertEqual([((), {"cafile": str(bundle)})], load_locations.calls)

    def test_registry_tls_verification_is_enabled_by_default_and_can_be_disabled_explicitly(self):
        with environment({}, remove=("ARTIFACTORY_TLS_VERIFY",)):
            self.assertTrue(deploy.registry_tls_verify_enabled())
        with environment({"ARTIFACTORY_TLS_VERIFY": "false"}):
            context = deploy.registry_ssl_context()
            self.assertFalse(context.check_hostname)
            self.assertEqual(deploy.ssl.CERT_NONE, context.verify_mode)

    def test_image_manifest_comparison_accepts_recompressed_layers_only_with_same_config(self):
        local = json.dumps({"config": {"digest": "sha256:config"},
                            "layers": [{"digest": "sha256:local", "size": 100}]}).encode()
        recompressed = json.dumps({"config": {"digest": "sha256:config"},
                                   "layers": [{"digest": "sha256:registry", "size": 90}]}).encode()
        different_image = json.dumps({"config": {"digest": "sha256:other"},
                                      "layers": [{"digest": "sha256:registry", "size": 90}]}).encode()
        self.assertTrue(deploy.image_manifests_match(local, recompressed))
        self.assertFalse(deploy.image_manifests_match(local, different_image))

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
        self.assertEqual("linux/amd64", deploy.load_config()["target_platform"])
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
        self.assertTrue(all(any(param["name"] == "target-platform" and
                                param["value"] == "linux/amd64"
                                for param in task["params"]) for task in build_tasks))

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
        self.assertIn("kubernetes.io/arch: amd64", build)
        self.assertIn('[ "$TARGET_PLATFORM" = linux/amd64 ]', build)
        self.assertIn("${TARGET_PLATFORM#linux/}", build)
        self.assertNotIn("buildah bud", build)
        publish = (SCRIPT.parent / "tekton/tasks/publish-pending-image.yaml").read_text()
        self.assertIn("docker-archive:$artifact", publish)
        self.assertIn("staged artifact has missing or unsupported platform metadata", publish)
        self.assertIn("skopeo inspect --format '{{.Os}}/{{.Architecture}}'", publish)


if __name__ == "__main__":
    unittest.main()
