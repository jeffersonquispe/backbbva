# ARIA OKD application manifests

These are Kustomize bases for application infrastructure only. Argo CD,
namespaces, registry access, and TLS trust are platform-managed prerequisites and
are intentionally absent. Runtime secrets are plain Kubernetes `Secret`s created
out-of-band (see below) — there is no OpenBao / Secrets Store CSI dependency.

Backend images (`api`, `worker`, `scheduler`, `test-worker`, `simulator-worker`,
`mcp`) are pulled from
`artifactory.globaldevtools.bbva.com:443/co-genai-public-cloud-docker-local/aria-genai/co-backend-aria-{api|worker|event-simulator-worker|mcp}:latest`,
built from `deploy/local/docker/Dockerfile.*.okd`. The frontend image is
`.../aria-genai/co-frontend-app-aria-frontend:latest`, same repo. Third-party images are pulled
straight from public registries (the cluster has internet egress):

| Component | Image |
| --- | --- |
| nginx proxy | `docker.io/nginxinc/nginx-unprivileged:1.27-alpine` |
| Redis | `docker.io/library/redis:7.2-alpine` |
| OpenSearch | `docker.io/opensearchproject/opensearch:2.13.0` |
| DynamoDB local | `docker.io/amazon/dynamodb-local:latest` |
| OTLP Collector | `artifactory.globaldevtools.bbva.com:443/public.ecr.aws-remote/aws-observability/aws-otel-collector:v0.43.2` (via Artifactory) |
| MinIO | `cgr.dev/chainguard/minio:latest` — upstream `minio/minio` is no longer publicly pullable from Docker Hub/Quay |

`OTEL_ENDPOINT` points every workload at the namespace OTLP Collector, `http://otel-collector:4317` (`observability/otel-collector/`, decision D5). The Collector image is the AWS Distro for OpenTelemetry (`aws-otel-collector`) pulled through Artifactory's `public.ecr.aws-remote`. **Its upstream backend is still a placeholder**: it exports to the `debug` exporter (sampled, pod logs) and to `otlp/upstream` -> `OTLP_UPSTREAM_ENDPOINT` in `aria-otel-collector-config`, which must be set to the real BBVA observability endpoint (plus TLS/auth) before telemetry leaves the namespace. PVCs use the `ceph-rbd` storage class. Initial resource values are
development defaults, not production sizing.

`dynamodb-local` is documented as a compatibility risk: the local Compose stack
runs it as root. This base does not grant privileged/root execution; validate the
selected image under OKD arbitrary-UID SCC before deployment.

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
| worker | `aria-worker-runtime` | AWS, Dynamo, and object-storage keys, `OPENAI_KEY` |
| test worker | `aria-test-worker-runtime` | AWS, Dynamo, and object-storage keys, `OPENAI_KEY` |
| scheduler | — | no application secret required |
| simulator worker | `aria-simulator-worker-runtime` | `EVENT_SIMULATOR_ARIA_API_TOKEN`, `DYNAMO_ACCESS_KEY`, `DYNAMO_SECRET_KEY`, `OPENAI_KEY` |
| MinIO | `aria-minio-runtime` | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` |
| OpenSearch | `aria-opensearch-runtime` | `OPENSEARCH_INITIAL_ADMIN_PASSWORD` |

Redis and DynamoDB are configured without credentials and need no Secret.
Changing a Secret value does not restart pods: run
`oc rollout restart deployment/<name>` (or `statefulset/<name>`) afterwards.
