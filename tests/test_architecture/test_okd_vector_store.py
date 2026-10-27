from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKERS = ROOT / "deploy/okd/iac_celery/computation/celery-workers"


def load(path):
    return yaml.safe_load(path.read_text())


def test_okd_test_workers_can_query_the_same_vector_store_as_production():
    main = load(WORKERS / "worker/configmap.yaml")["data"]
    test = load(WORKERS / "test-worker/configmap.yaml")["data"]
    simulator = load(WORKERS / "simulator-alert-worker/configmap.yaml")["data"]
    for key in (
        "OPENSEARCH_ENDPOINT",
        "OPENSEARCH_AUTH_MODE",
        "OPENSEARCH_INDEX",
        "EMBEDDING_DIMENSIONS",
    ):
        assert main[key] == test[key] == simulator[key]
    deployment = load(WORKERS / "test-worker/deployment.yaml")
    env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
    refs = {item["name"]: item.get("valueFrom", {}).get("secretKeyRef") for item in env}
    secret = load(WORKERS / "test-worker/secret.example.yaml")["stringData"]
    for key in ("OPENSEARCH_USERNAME", "OPENSEARCH_PASSWORD"):
        assert refs[key] == {"name": "aria-worker-test-runtime", "key": key}
        assert key in secret


def test_okd_retention_has_one_beat_and_matching_configuration():
    scheduler = load(WORKERS / "scheduler/deployment.yaml")
    assert scheduler["spec"]["replicas"] == 1
    assert scheduler["spec"]["strategy"]["type"] == "Recreate"
    config = load(WORKERS / "worker/configmap.yaml")["data"]
    assert config["VECTOR_STORE_GENERATION_CLEANUP_ENABLED"] == "true"
    assert config["VECTOR_STORE_GENERATION_RETENTION_DAYS"] == "14"
    assert config["VECTOR_STORE_ROLLBACK_CONFIGURATIONS"] == "2"


def test_okd_worker_image_contains_context_prompt_upgrade_tool():
    dockerfile = (ROOT / "deploy/local/docker/Dockerfile.worker.okd").read_text()
    assert (
        "scripts/upgrade_agent_context_prompts.py ./scripts/upgrade_agent_context_prompts.py"
        in dockerfile
    )
