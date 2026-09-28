"""Event-simulator worker entrypoint (simulator/celery/) - the self-
rescheduling tick loop that generates synthetic fraud-alert events 24/7. Its
own scenario CRUD/lifecycle control-plane lives in aria-api instead (see
entrypoint/api/routers/scenarios_router.py) - this package only ever reads
scenario config from the shared DynamoDB table it and aria-api both write to
(simulation_scenario_repository.py). Independent from aria-api's
entrypoint/api/ and aria-worker's entrypoint/worker/ Python code: this
package never imports either, and reaches aria-api only over plain HTTP
through the platform_gateway/http adapters (full isolation of the
generation loop itself is an explicit design goal, see backend CLAUDE.md and
the alert_dispatch_gateway / event_sink / dataset_reader_gateway port
docstrings)."""
