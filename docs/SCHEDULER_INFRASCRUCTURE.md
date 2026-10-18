# Scheduler, retention and processing infrastructure

## Runtime topology

ARIA uses Celery with Redis. A single `scheduler` service runs Celery Beat
and only publishes maintenance tasks. It must have exactly one replica per
environment. The workers execute the published tasks.

| Workload | Queue | Worker | Scheduling |
| --- | --- | --- | --- |
| Production, manual and simulator workflows | `CELERY_DEFAULT_QUEUE` (`default`) | `worker` | dispatched by the API/simulator |
| CSV test runs | `CELERY_TEST_QUEUE` (`test`) | `test-worker` | dispatched by the test-run API |
| Simulator ticks | `event_simulation` on Redis DB 2 | `simulator-worker` | self-rescheduling per scenario |
| Reconciliation and test cleanup | `default` | `worker` | Celery Beat |

The dedicated test queue and worker isolate test capacity from production.
They still share the local Redis service and DynamoDB tables; production must
use separate Redis credentials/database, worker deployment, and DynamoDB
tables or account when regulatory isolation is required.

## Scheduled tasks

- `async_operations.reconcile`: every
  `CELERY_RECONCILE_INTERVAL_SECONDS` (60 by default), up to
  `CELERY_RECONCILE_LIMIT` operations per run.
- `test_runs.cleanup`: every
  `CELERY_TEST_RUN_CLEANUP_INTERVAL_SECONDS` (3600 by default). It reads the
  live operational settings and never deletes `PENDING` or `RUNNING` runs.
  `manual` disables automatic deletion; `oldest` deletes oldest terminal
  runs; `failed-first` prioritizes failed terminal runs. Deletion is the
  existing idempotent cascade by `run_id`.

The simulator tick intentionally remains self-rescheduling. Beat must not
replace it, because a global scan would reduce cadence precision and need a
distributed duplicate-tick lock. A future reconciliation task can recover
stalled scenarios after an agreed grace period.

## Scaling decision

Use Celery workers as the execution substrate. The queue split lets an
orchestrator scale `worker` and `test-worker` independently from queue depth,
age of oldest message, CPU, memory and LLM-provider limits. `task_acks_late`
and prefetch 1 are already configured for fair dispatch.

Knative is suitable as the deployment/autoscaling layer around long-running
Celery workers only if it preserves a minimum warm replica and graceful
draining. Lambda is not suitable for the present workflows: they make
long-lived LLM calls, need retry/observability continuity, and would require
moving task orchestration out of Celery.

`DEPLOYMENT_TYPE` selects the infrastructure pattern (`docker` by default,
`okd` in the OKD manifests). Docker Compose keeps replicas operator-managed;
scale the `aria-worker-main` and `aria-worker-test` services explicitly with
`docker compose up --scale`. Compose has no queue-aware autoscaler.

OKD uses KEDA Redis list scalers for the `default` and `test` queues. A
one-minute capacity controller reads `OperationalSettings` from DynamoDB and
patches only those two KEDA `ScaledObject` resources: `max_instances` sets
the production worker ceiling, `max_test_instances` sets the test worker
ceiling, and `auto_scale=true` lets each worker scale to zero while idle.
`auto_scale=false` pins both at one replica. KEDA must already be installed
in the OKD cluster. The controller's service account is limited
to reading and patching those named ScaledObjects. Changes take effect within
one reconciliation interval. The Argo CD Application must ignore differences
for `spec.minReplicaCount` and `spec.maxReplicaCount` on the ScaledObjects and
`spec.replicas` on both worker Deployments so GitOps does not undo scaling.

## Fraud-history retention: required decision

No fraud-history repository, archive format, or cold-storage location exists
in this backend. The two retention values on `InfraSettings` are configuration
only. Therefore there is deliberately no deletion task for fraud history.

Before enabling it, define all of the following:

1. The authoritative records and their legal-hold/audit exclusions.
2. The cold-store bucket, encryption/key policy, partition format and access
   path.
3. Archive verification and idempotency before deleting the hot record.
4. DynamoDB TTL/index strategy and the retention owner for backups.

The implementation should then archive verified records after
`fraud_history_db_retention_days`, purge the cold copy after
`fraud_history_cold_storage_retention_months`, and emit OTLP counts/errors.

## Schema contract

Test runs already invoke the production workflow and pin the same versioned
configuration. The input contract is the alert parser's raw field schema;
datasets must be validated against it before a test run is accepted. Test-only
prompt/model overrides remain explicit metadata and must not change the raw
alert schema. This keeps results comparable while allowing controlled
experimentation.
