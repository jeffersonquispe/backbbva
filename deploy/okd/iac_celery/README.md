# ARIA OKD application manifests

These are Kustomize bases for application infrastructure only. Argo CD,
namespaces, registry access, and TLS trust are platform-managed prerequisites and
are intentionally absent. Runtime secrets are plain Kubernetes `Secret`s created
out-of-band (see below) — there is no OpenBao / Secrets Store CSI dependency.

Backend images (`api`, `aria-worker-main`, `aria-worker-training`,
`aria-worker-scheduler`, `aria-worker-test`, `aria-worker-simulator`, `mcp`)
are pulled from
`artifactory.globaldevtools.bbva.com:443/co-genai-public-cloud-docker-local/aria-genai/co-backend-aria-{api|worker|training-worker|event-simulator-worker|mcp}:latest`,
built from `deploy/local/docker/Dockerfile.*.okd`. The training worker has
its own dependency set and image. The frontend image is
`.../aria-genai/co-frontend-app-aria-frontend:latest`, same repo. Third-party images are pulled
straight from public registries (the cluster has internet egress):

| Component | Image |
| --- | --- |
| nginx proxy | `docker.io/nginxinc/nginx-unprivileged:1.27-alpine` |
| Redis | `docker.io/library/redis:7.2-alpine` |
| OpenSearch | `docker.io/opensearchproject/opensearch:2.19.1` |
| DynamoDB local | `docker.io/amazon/dynamodb-local:latest` |
| OTLP Collector | `artifactory.globaldevtools.bbva.com:443/public.ecr.aws-remote/aws-observability/aws-otel-collector:v0.43.2` (via Artifactory) |
| Tempo / Loki / Prometheus / Grafana | `docker.io/grafana/tempo:2.6.1`, `docker.io/grafana/loki:3.3.2`, `docker.io/prom/prometheus:v3.0.1`, `docker.io/grafana/grafana:11.4.0` (same versions as the local Compose stack) |
| MinIO | `cgr.dev/chainguard/minio:latest` — upstream `minio/minio` is no longer publicly pullable from Docker Hub/Quay |

`OTEL_ENDPOINT` points every workload at the namespace OTLP Collector, `http://otel-collector:4317` (`observability/otel-collector/`, decision D5). The Collector image is the AWS Distro for OpenTelemetry (`aws-otel-collector`) pulled through Artifactory's `public.ecr.aws-remote`. **Its upstream backend is still a placeholder**: it exports to the `debug` exporter (sampled, pod logs) and to `otlp/upstream` -> `OTLP_UPSTREAM_ENDPOINT` in `aria-otel-collector-config`, which must be set to the real BBVA observability endpoint (plus TLS/auth) before telemetry leaves the namespace. PVCs use the `ceph-rbd` storage class. Initial resource values are
development defaults, not production sizing.

OKD worker capacity is manual: there is no autoscaler (no KEDA). Size it
from expected traffic by changing `spec.replicas` of the `aria-worker-main`
(default queue, `--concurrency=10`, so ~10 alerts in flight per replica) and
`aria-worker-test` Deployments, or with `oc scale deployment/aria-worker-main
--replicas=N`. Argo CD must ignore `/spec/replicas` on those two Deployments if
scaling by hand outside Git. The `max_instances`, `auto_scale` and
`max_test_instances` operational settings are not applied in OKD. Docker
Compose also uses explicit `--scale` values.

`dynamodb-local` is documented as a compatibility risk: the local Compose stack
runs it as root. This base does not grant privileged/root execution; validate the
selected image under OKD arbitrary-UID SCC before deployment.

## Observability group (`observability/`)

Mirrors the observability services of `deploy/local/docker/docker-compose.yml`.
Applications still only know `OTEL_ENDPOINT`; the Collector fans out:

```
otel-collector -> tempo (traces, OTLP gRPC)
               -> loki (logs, OTLP/HTTP)
               -> prometheus (metrics, OTLP/HTTP, --web.enable-otlp-receiver)
               -> phoenix (traces, OTLP/HTTP; own queue, an outage never blocks the others)
               -> otlp/upstream (still the BBVA placeholder)
tempo, loki -> observability-minio (buckets created by the observability-minio-init Argo Sync hook)
grafana     -> prometheus, tempo, loki   (exposed by nginx at /grafana/, no anonymous access)
phoenix     -> phoenix-db (PostgreSQL StatefulSet, 20Gi ceph-rbd PVC)   (exposed by nginx at /phoenix/, NO login yet)
```

**Phoenix (trace UI).** Trace identity: `trace_id` = workflow execution UUID (no
dashes), step spans carry `aria.workflow.step_id`, LLM/embedding/tool spans
`aria.run_id`. Retention is `PHOENIX_RETENTION_DAYS` (days, default 30, `0` =
forever) in `aria-phoenix-config`; it is not a backup, so back up the
`phoenix-db` PVC with the platform. Before the first sync create the secret
(`oc create secret generic aria-phoenix-runtime ...`; `artifactory-auth` must
already exist). Images, both through Artifactory's Docker Hub remote:
`artifactory.globaldevtools.bbva.com:443/hub.docker.com-remote/arizephoenix/phoenix:version-19.21.0`
and `.../hub.docker.com-remote/library/postgres:16`. Postgres runs as fixed UID
999 with an `anyuid` RoleBinding on `phoenix-db-sa` (same pattern as OpenSearch)
and the PVC `phoenix-db-data` (20Gi, `ceph-rbd`). Verified: the Collector config
with `otlphttp/phoenix` starts on both the ADOT image used here
(`aws-otel-collector:v0.43.2`) and `otel/opentelemetry-collector-contrib:0.116.1`
(local). Open points for platform: that those two Artifactory paths exist and
are pullable (not reachable from outside the VPN, so not checked), TLS and
authentication for `/phoenix/`, and restricting the Route. Phoenix's UI also calls `static.scarf.sh` and `sessions.bugsnag.com` from
the browser; block them at the network level if required.

`observability-minio` is separate from the application `minio`. Grafana
provisioning and dashboards under `observability/grafana/` are copies of
`deploy/local/docker/observability/grafana/`; keep both in sync. Unlike local,
Prometheus receives metrics by OTLP push instead of scraping the Collector, and
the Collector config does not include the `spanmetrics` connector (the ADOT image
may not ship it), so the RED panels built on `traces_span_metrics_*` stay empty
until the Collector image is swapped for `otel/opentelemetry-collector-contrib`.

`aria-evaluation-worker` (queue `reasoning-evaluation`, concurrency 2) runs the LLM-judge of
the agent's reasoning, silent and independent of alert processing: a slow or down
evaluator never delays or blocks an alert. `aria-agent-worker` (queue `agent`, concurrency 1), `aria-agent-chat-worker` (queue
`agent-chat`, concurrency 4: assistant chat replies, so an optimizer candidate never
delays an answer) and `aria-agent-beat` reuse the
`co-backend-aria-worker` image, `aria-worker-main-config` and
`aria-worker-main-runtime`. Beat uses `Recreate` so it never runs twice.

## Required Secrets

Each workload reads its credentials through `secretKeyRef` from a Secret that
must exist in the namespace **before** Argo CD syncs. Every component with
credentials ships a `secret.example.yaml` template (key list + `oc create secret`
one-liner). The templates are deliberately **not** in any `kustomization.yaml`,
so Argo CD never commits, syncs, or overwrites real values.

| Workload | Secret | Keys |
| --- | --- | --- |
| API | `aria-api-runtime` | `AUTH_JWT_SECRET`, `AUTH_BOOTSTRAP_TOKEN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `DYNAMO_ACCESS_KEY`, `DYNAMO_SECRET_KEY`, `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY`, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`, `OPENAI_KEY` |
| MCP | `aria-mcp-runtime` | AWS, Dynamo, and object-storage keys |
| `aria-worker-main` | `aria-worker-main-runtime` | AWS, Dynamo, object-storage, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`, `OPENAI_KEY` |
| `aria-worker-training` | `aria-worker-main-runtime` | AWS, Dynamo, and object-storage keys, `OPENAI_KEY` |
| `aria-worker-test` | `aria-worker-test-runtime` | AWS, Dynamo, object-storage, `OPENSEARCH_USERNAME`, `OPENSEARCH_PASSWORD`, `OPENAI_KEY` |
| `aria-worker-scheduler` | — | no application secret required |
| `aria-worker-simulator` | `aria-worker-simulator-runtime` | `EVENT_SIMULATOR_ARIA_API_TOKEN`, `DYNAMO_ACCESS_KEY`, `DYNAMO_SECRET_KEY`, `OPENAI_KEY` |
| MinIO | `aria-minio-runtime` | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` |
| OpenSearch | `aria-opensearch-runtime` | `OPENSEARCH_INITIAL_ADMIN_PASSWORD` |
| `aria-agent-worker`, `aria-agent-chat-worker`, `aria-evaluation-worker`, `aria-agent-beat` | `aria-worker-main-runtime` | same as `aria-worker-main` |
| Observability MinIO, Tempo, Loki, bucket init | `aria-observability-minio-runtime` | `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| Phoenix, phoenix-db | `aria-phoenix-runtime` | `PHOENIX_DB_USER`, `PHOENIX_DB_PASSWORD`, `PHOENIX_DB_NAME` (template: `observability/phoenix/secret.example.yaml`) |
| Grafana | `aria-grafana-runtime` | `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` |

Redis and DynamoDB are configured without credentials and need no Secret.
Changing a Secret value does not restart pods: run
`oc rollout restart deployment/<name>` (or `statefulset/<name>`) afterwards.

## Vector Store generations and agent context

The main, test, and simulator-alert workers use 3,072-dimensional embeddings.
The test worker connects to the same OpenSearch service as the main worker and
reads its credentials from `aria-worker-test-runtime`. Add the two OpenSearch
keys to an existing test-worker Secret before applying this Deployment; its
`secret.example.yaml` is a template only. The main worker runs the daily
generation cleanup at 04:30 Bogotá (14-day retention, two rollback
configurations). The main Celery beat uses `Recreate` so two schedulers do not
publish the same sweep during a rollout.

For an existing environment, coordinate a maintenance window and back up
DynamoDB and OpenSearch first. Build and select API and worker image tags that
contain the generation and prompt-upgrade code; the image tags in these
manifests do not automatically change when source changes. Before allowing
alert traffic onto the new code, run from a newly deployed main-worker pod:

```sh
oc exec deployment/aria-worker-main -- python -m src.infrastructure.entrypoint.worker.vector_store_generations migrate
# Inspect the report; resolve every segment_tools_unresolved entry first.
oc exec deployment/aria-worker-main -- python -m src.infrastructure.entrypoint.worker.vector_store_generations migrate --apply
# A second dry run verifies that nothing remains to migrate.
oc exec deployment/aria-worker-main -- python -m src.infrastructure.entrypoint.worker.vector_store_generations migrate

oc exec deployment/aria-worker-main -- python scripts/upgrade_agent_context_prompts.py
# Review custom_prompt or other reported conflicts before applying.
oc exec deployment/aria-worker-main -- python scripts/upgrade_agent_context_prompts.py --apply
```

The prompt command upgrades known defaults only and preserves older versions
for pinned sessions. Integrate customized prompts manually. Migration changes
configuration and Vector Store pins: old H11/H12 evidence may need to be
repeated; see `docs/VECTOR_STORE_GENERATIONS.md`. These operations have not
been executed in OKD by this change.
