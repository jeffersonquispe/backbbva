# Model serving and training workers

Alert workflows run on the `default` Celery queue. They request XGBoost scores
from the internal model-serving service at `MCP_BASE_URL`; the scoring request
contains alert/model IDs, and the serving service reads the canonical alert
and model bundle itself. The bundle is loaded at MCP startup and reused from a
single-entry cache. When scoring is unavailable, alert review keeps its
existing LLM-only fallback.

Model training is dispatched to the `model-training` queue. Only the dedicated
`aria-worker-training` deployment consumes that queue, with Celery concurrency set
to one so training cannot compete with alert workflows in the same process.
`aria-worker-main` explicitly listens only to `default`.
Its local and OKD worker commands set concurrency to ten. The training,
test, and simulator workers each run one Celery process by default, avoiding
Celery's host-CPU-based default process count.

The MCP `/internal/score` HTTP route is internal service traffic alongside the
MCP tools. OKD network policy permits the API and `aria-worker-main` to reach
the MCP pod. Local Compose starts `aria-worker-training` against the same
Redis broker.

The main worker image has a reduced dependency set: model scoring is served
by MCP and model training runs in the dedicated training worker. The main
worker retains pandas for optional history research.
Resource requests and limits should be reduced only after measuring the
Docker memory peak with ten representative concurrent alert workflows.

For a point-in-time local worker reading, run `make local-worker-stats`.
