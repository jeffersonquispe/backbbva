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

`OperationalSettings.max_instances`, `auto_scale` and
`max_test_instances` cannot safely change process replicas from application
code. Applying them requires a chosen control plane and credentials (for
example Kubernetes HPA/KEDA, ECS, or a managed worker platform). Until that
is selected, they remain desired-capacity settings rather than enforcement.

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
