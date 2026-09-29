# ARIA OKD application manifests

These are Kustomize bases for application infrastructure only. Argo CD, OpenBao,
the Secrets Store CSI driver, its OpenBao provider, namespaces, registry access,
and TLS trust are platform-managed prerequisites and are intentionally absent.

Replace before promotion: `REGISTRY_REPLACE_ME`, `IMAGE_TAG_REPLACE_ME`,
`STORAGE_CLASS_REPLACE_ME`, and `OPENBAO_URL_REPLACE_ME`. Initial resource
values are development defaults, not production sizing. The deployed OpenBao CSI
provider must support `provider: openbao` (OpenBao CSI provider 2.x); it uses
`roleName`, `baoAddress`, and `objects`.

`dynamodb-local` is documented as a compatibility risk: the local Compose stack
runs it as root. This base does not grant privileged/root execution; validate the
selected image under OKD arbitrary-UID SCC before deployment.

## Expected OpenBao access

| Workload | ServiceAccount / role | Secret paths and keys |
| --- | --- | --- |
| API | `aria-api` / `aria-api` | `secret/data/aria/api/auth`: `AUTH_JWT_SECRET`, `AUTH_BOOTSTRAP_TOKEN`; `.../storage`: AWS, Dynamo, and object-storage keys; `.../opensearch`: username/password |
| MCP | `aria-mcp` / `aria-mcp` | `secret/data/aria/mcp/storage`: AWS, Dynamo, and object-storage keys |
| worker | `aria-worker` / `aria-worker` | `secret/data/aria/workers/common`: AWS, Dynamo, object-storage keys |
| test worker | `aria-test-worker` / `aria-test-worker` | `secret/data/aria/workers/common`: AWS, Dynamo, object-storage keys |
| scheduler | `aria-scheduler` / `aria-scheduler` | `secret/data/aria/workers/scheduler`: no application secret currently required (CSI identity mount retained for future scheduler secrets) |
| simulator worker | `aria-simulator-worker` / `aria-simulator-worker` | `secret/data/aria/workers/simulator-worker`: `EVENT_SIMULATOR_ARIA_API_TOKEN`, Dynamo keys |
| MinIO | `aria-minio` / `aria-minio` | `secret/data/aria/infrastructure/minio`: `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` |
| OpenSearch | `aria-opensearch` / `aria-opensearch` | `secret/data/aria/infrastructure/opensearch`: `OPENSEARCH_INITIAL_ADMIN_PASSWORD` |

Redis and DynamoDB have ServiceAccounts but no OpenBao SecretProviderClass because
this base configures neither with credentials. Every `secretproviderclass.yaml`
identifies the role, paths, and keys in machine-readable form.
