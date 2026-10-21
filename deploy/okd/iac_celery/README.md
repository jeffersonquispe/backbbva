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

OKD capacity scaling requires the KEDA operator and Redis scaler CRDs to be
installed by the platform team. The `aria-capacity-controller` CronJob reads
the operational settings from DynamoDB every minute and can patch only the
`aria-worker-main` and `aria-worker-test` ScaledObjects. Configure the Argo CD
Application to ignore differences for `/spec/minReplicaCount` and
`/spec/maxReplicaCount` on those two resources, and `/spec/replicas` on both
worker Deployments. Otherwise GitOps reconciliation can overwrite the
runtime capacity settings. Docker Compose has no queue autoscaler and uses
explicit `--scale` values.

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
               -> otlp/upstream (still the BBVA placeholder)
tempo, loki -> observability-minio (buckets created by the observability-minio-init Argo Sync hook)
grafana     -> prometheus, tempo, loki   (exposed by nginx at /grafana/, no anonymous access)
```

`observability-minio` is separate from the application `minio`. Grafana
provisioning and dashboards under `observability/grafana/` are copies of
`deploy/local/docker/observability/grafana/`; keep both in sync. Unlike local,
Prometheus receives metrics by OTLP push instead of scraping the Collector, and
the Collector config does not include the `spanmetrics` connector (the ADOT image
may not ship it), so the RED panels built on `traces_span_metrics_*` stay empty
until the Collector image is swapped for `otel/opentelemetry-collector-contrib`.

`aria-agent-worker` (queue `agent`, concurrency 1) and `aria-agent-beat` reuse the
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
| `aria-worker-main` | `aria-worker-main-runtime` | AWS, Dynamo, and object-storage keys, `OPENAI_KEY` |
| `aria-worker-training` | `aria-worker-main-runtime` | AWS, Dynamo, and object-storage keys, `OPENAI_KEY` |
| `aria-worker-test` | `aria-worker-test-runtime` | AWS, Dynamo, and object-storage keys, `OPENAI_KEY` |
| `aria-worker-scheduler` | — | no application secret required |
| `aria-worker-simulator` | `aria-worker-simulator-runtime` | `EVENT_SIMULATOR_ARIA_API_TOKEN`, `DYNAMO_ACCESS_KEY`, `DYNAMO_SECRET_KEY`, `OPENAI_KEY` |
| MinIO | `aria-minio-runtime` | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` |
| OpenSearch | `aria-opensearch-runtime` | `OPENSEARCH_INITIAL_ADMIN_PASSWORD` |
| `aria-agent-worker`, `aria-agent-beat` | `aria-worker-main-runtime` | same as `aria-worker-main` |
| Observability MinIO, Tempo, Loki, bucket init | `aria-observability-minio-runtime` | `S3_ACCESS_KEY`, `S3_SECRET_KEY` |
| Grafana | `aria-grafana-runtime` | `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD` |

Redis and DynamoDB are configured without credentials and need no Secret.
Changing a Secret value does not restart pods: run
`oc rollout restart deployment/<name>` (or `statefulset/<name>`) afterwards.
