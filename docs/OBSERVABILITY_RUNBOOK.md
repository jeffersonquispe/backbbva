# Runbook de observabilidad (O1)

Runbook operativo de la telemetría de ARIA. Contexto y decisiones:
`docs/OBSERVABILITY_STRATEGY.md`.

## Telemetría técnica (M5)

### Cómo llega cada señal

App → OTLP (`OTEL_ENDPOINT`, única variable que conoce la app) → Collector →
backends. Sin `OTEL_ENDPOINT` (valor vacío) no sale nada: trazas, métricas y
logs comparten esa compuerta.

| Señal | Origen en la app | Local (Collector → …) | OKD |
| --- | --- | --- | --- |
| Trazas | `MonitoringPort.start(...)` | Tempo | `debug` + placeholder `otlp/upstream` |
| RED por span | conector `spanmetrics` del Collector (`traces_span_metrics_*`) | Prometheus | — (sólo local por ahora) |
| Métricas explícitas | `gen_ai.client.*` al cerrar spans `llm`/`embedding`; `aria.*` vía `MonitoringPort.record_*` | Prometheus | `debug` + placeholder |
| Logs | `LoggingHandler` OTLP en el logger raíz (lo instala `get_monitoring()`), con `trace_id`/`span_id` | Loki (`/otlp`, `trace_id` como structured metadata → enlace a Tempo) | `debug` + placeholder |

Nombres en Prometheus: puntos → `_`, sufijo de unidad (`_seconds`) y `_total`
en contadores, p. ej. `gen_ai_client_operation_duration_seconds_bucket`,
`aria_research_calls_total`, `aria_metrics_rollup_drift`. El `service.name`
de cada proceso queda en la etiqueta `exported_job`.

Dimensiones permitidas en métricas: sólo valores de pocos posibles (paso,
resultado, modelo, proveedor, fuente). **Nunca** `customer_id`, ids de
alerta ni monto exacto.

### Stack local

```bash
make local-docker-run          # inicia la aplicación y observabilidad
make observability-up          # inicia sólo observabilidad si hace falta
make observability-down        # detiene observabilidad; conserva volúmenes
```

Dashboards versionados en `deploy/local/docker/observability/grafana/dashboards/`
(`service-overview`, `llm-overview`); reglas de alerta en
`deploy/local/docker/observability/grafana/provisioning/alerting/aria-rules.yaml`
(carpeta **ARIA** en *Alerting → Alert rules*). Tras editar las reglas:

```bash
curl -X POST -u admin:admin http://localhost:3000/api/admin/provisioning/alerting/reload
```

### Forzar cada regla de alerta en local

Con el stack arriba, `force_alerts.py` emite telemetría a través del adapter
real (`get_monitoring()`), cada 15 s, durante `--minutes` (12 por defecto):

```bash
python deploy/local/docker/observability/force_alerts.py <escenario> [--minutes N]
```

Usa por defecto `GENAI_ENVIRONMENT=local`, `API_V0_STR=/api/v0` y
`OTEL_ENDPOINT=http://localhost:4317`. Se ve en *Alerting → Alert rules*:
`Pending` y luego `Firing` al cumplirse el `for`. Varios escenarios pueden
correr a la vez en procesos distintos, salvo `dead-mans-switch` (necesita que
nadie registre workflows en los últimos 30 min). `demo` llena los dashboards
sin disparar reglas.

| Regla (uid) | Condición | Escenario | Dispara en |
| --- | --- | --- | --- |
| <a id="aria-workflow-failing"></a>Workflow fallando (`aria-workflow-failing`) | `FAILED` > 5 % de los workflows, 15 min | `workflow-failing` (50 % FAILED) | ~6 min |
| <a id="aria-sla-at-risk"></a>SLA en riesgo (`aria-sla-at-risk`) | p95 de `aria.workflow.duration{step=workflow}` > 300 s, 15 min | `sla-at-risk` (runs de 420 s) | ~11 min |
| <a id="aria-dead-mans-switch"></a>Dead man's switch (`aria-dead-mans-switch`) | `aria.agent.enabled == 1` y 0 workflows en 30 min | `dead-mans-switch` (agente ON, sin workflows) | ~6 min |
| <a id="aria-llm-errors"></a>LLM caído (`aria-llm-errors`) | > 10 % de `gen_ai.client.operation.duration` con `error.type`, 5 min | `llm-down` (spans `llm` que lanzan `ConnectionError`) | ~3 min |
| <a id="aria-llm-slow"></a>LLM lento (`aria-llm-slow`) | p95 de `gen_ai.client.operation.duration` > 30 s, 5 min | `llm-slow` (llamadas de 31 s) | ~6 min |
| <a id="aria-research-degraded"></a>Investigación degradada (`aria-research-degraded`) | > 20 % de `aria.research.calls` no-`ok` por fuente, 15 min | `research-degraded` (2/3 timeout/failed) | ~6 min |
| <a id="aria-analyst-queue-stuck"></a>Cola de analistas atascada (`aria-analyst-queue-stuck`) | `aria.analyst_queue.oldest_age` > 900 s | `analyst-queue-stuck` (1200 s) | ~2 min |
| <a id="aria-no-capacity"></a>Sin capacidad (`aria-no-capacity`) | `aria.capacity.available` = 0 (analista o voicebot) en horario operativo, 10 min | `no-capacity` (0 analistas) | ~11 min |
| <a id="aria-rollup-drift"></a>Drift de agregados dos días seguidos (`aria-rollup-drift`) | `aria.metrics.rollup_drift` > 0 ahora **y** hace 24 h, 1 h | `rollup-drift` + ver nota | 25 h |

Nota sobre `aria-rollup-drift`: la regla compara contra `offset 24h`, así que
no se puede forzar en minutos sin tocarla. Para probarla, corre
`rollup-drift --minutes 20`, cambia temporalmente en `aria-rules.yaml`
`offset 24h` → `offset 5m` y `for: 1h` → `for: 1m`, recarga el
aprovisionamiento (curl de arriba) y revierte el cambio al terminar.

Las reglas tienen `noDataState: OK`: si una serie no existe (productor sin
cablear o proceso parado) la regla queda en `Normal`, no en alerta.

### Productores (dónde se cablea cada señal)

Todos los métodos de `MonitoringPort` ya tienen productor. Si una regla
queda sin datos, el proceso que la alimenta está parado (las reglas tienen
`noDataState: OK`):

- `record_workflow_duration(step, outcome, duration_seconds)` → runner del
  workflow (`infrastructure/workflows/celery/alert_review_workflow.py`):
  `_run_step` por paso (`outcome` = `SUCCEEDED`/`FAILED`) y `run()` por
  corrida completa con `step=WORKFLOW_TOTAL_STEP` y `outcome` = estado final
  de la alerta (`CLOSED`/`ESCALATED`/`FAILED`/`SKIPPED`).
- `record_research_call(source, outcome)` → `TimeBoundedResearchAgent`
  (`application/use_cases/research/delegated_research.py`), el envoltorio
  común de Vector Store (`search_vector_store`) e historial (`history_pandas`):
  `ok` (ejecutada), `failed` (falló o lanzó excepción), `timeout` (superó
  `timeout_seconds`). `skipped` no cuenta como llamada.
- `record_rollup_drift(data_type, level, drift)` → reconciliación diaria de
  agregados (`ReconcileAlertRollups`, R7); registra también `0` cuando cuadra.
- `record_operational_state(OperationalStateSnapshot(...))` → tarea de Beat
  `metrics.record_operational_state` (entrada `record-operational-state` en
  `celery_app.periodic_schedule`, cada 60 s, `expires=60`) → use case
  `RecordOperationalState` (`application/use_cases/metrics/record_operational_state.py`):
  agente ON/OFF (`OperationalSettings.agent_enabled`), horario operativo (la
  matriz de analistas planifica > 0 para la hora local actual), cola de
  analistas (`count_by_status(ESCALATED)` del índice de estado + edad del
  `created_at` más antiguo) y capacidad (`LiveOperationsCapacity`). Es
  también el latido del *dead man's switch*: si Beat o el worker se paran,
  la serie deja de llegar.

#### Spans con dimensiones (T2)

Nombres en un único módulo: constantes `ATTR_*` y
`span_dimension_attributes(snapshot)` en `application/ports/monitoring_port.py`
(`aria.origin`, `aria.segment`, `aria.channel`, `aria.subchannel`,
`aria.amount_tier`, `aria.configuration_id`, `aria.resolution_method`,
`aria.mark`, `aria.fraud_label`, `aria.status`), tomados de la foto
`AlertMetricsSnapshot`. **Prohibidos en spans**: `customer_id` y el monto
exacto (sólo viaja `aria.amount_tier`); lo verifica
`test_workflow_and_step_spans_carry_dimensions_never_customer_or_amount`.

| Span | Quién lo emite | Atributos propios |
| --- | --- | --- |
| `alert_review_workflow` | runner, una por intento | dimensiones (se refrescan tras cada evento de métricas), `aria.workflow.outcome` |
| `alert_review_workflow.<paso>` | runner, `_run_step` | `aria.workflow.step`, `aria.workflow.attempt` + dimensiones conocidas al empezar el paso |
| `alert.mark_set` | `RecordAlertMetricsEvent`, cuando `mark` sale de `pending` (ARIA, analista o voicebot) | `aria.mark`, `aria.resolution_method`, `aria.resolution_time_seconds` + dimensiones |
| `fraud_label.review` | `ReviewFraudLabel`, una por revisión (UI o CSV) | `aria.fraud_label`, `aria.fraud_label.previous`, `aria.fraud_review.channel`, `aria.fraud_review.count` + dimensiones (nunca `reviewed_by` ni la nota) |

`gen_ai.client.*` no necesita cableado: sale de los spans `llm`/`embedding`
que ya crean los unit of work de LangChain.

### OKD

Collector propio en el namespace (`deploy/okd/iac_celery/observability/otel-collector/`,
decisión D5); todas las cargas usan `OTEL_ENDPOINT=http://otel-collector:4317`.
Su destino real **aún no está definido**: exporta a `debug` (logs del pod,
muestreado) y a `otlp/upstream` → `OTLP_UPSTREAM_ENDPOINT` (placeholder en
`aria-otel-collector-config`). Hasta reemplazarlo, la telemetría no sale del
namespace y el Collector registra avisos de conexión al placeholder.

## Agregados de métricas: carga, retención y costo (Q3, A4, O2, O3)

Medido el 2026-10-02 contra un DynamoDB Local **desechable** (puerto 8012;
las tablas no tienen prefijo, así que nunca se corre contra el 8002 del stack).

```bash
make metrics-loadtest-up                       # contenedor aria-dynamodb-loadtest
make metrics-synthetic-load DAYS=90 PER_DAY=1500 WORKERS=1
make metrics-query-bench RUNS=12               # p50/p95 por endpoint, rango y filtros
make metrics-loadtest-down                     # borra contenedor y datos
```

`metrics_synthetic_load` crea alertas realistas (canal/subcanal, segmento,
monto lognormal en COP, perfil horario de Bogotá, rangos de monto configurados
a mitad de la ventana) y pasa **cada evento** por los writers reales con reloj
falso: `RecordAlertMetricsEvent` (CREATED → PRE_PROCESSED → WORKFLOW_FINISHED →
ANALYST_RESOLVED / VOICEBOT_COMPLETED → FRAUD_REVIEWED con 98 % en 4 días y
2 % hasta 6 meses) y `RecordWorkflowStepMetrics` para una muestra
(`--tech-sample`). Usa `WORKERS=1`: con varios procesos DynamoDB Local
serializa las transacciones y responde "timed out waiting for a lock".
Rendimiento local: ~20 alertas/s, ~75 eventos de métricas/s (un worker), así
que 90 × 1.5k (135k alertas) toma ~2 h; la medición se hizo con 3 días a
1.5k/día + 87 días a 100/día (11.5k alertas) y se extrapola abajo.

### Filas y tamaño

| `data_type` (día) | filas/día a 1.5k alertas | filas/día a 100 | bytes por fila (prom. / p95) |
| --- | --- | --- | --- |
| `alert` | ~600–970 (más combinaciones con rangos de monto) | ~148 | 660 / 985 |
| `workflow_step` (10 % de muestra) | ~810–890 | ~85 | 610 / 700 |
| `llm_call` (10 %) | ~480–520 | ~50 | 660 / 760 |
| `research_call` (10 %) | ~120–135 | ~10 | 560 / 590 |

- Con 11 dimensiones casi cada alerta cae en su propia combinación: una fila de
  día ≈ 0.6–0.7 alertas. Las filas de mes y año acumulan más horas (20+ medidas,
  p95 1.6–1.8 KB, máximo ~5.5 KB).
- Proyección a 1.5k/día y 100 % de pasos técnicos: ~1k filas `alert` + ~3–4k
  técnicas por día ≈ 2.5–3 MB/día; 90 días de filas de día ≈ 250 MB. Marcadores
  `apply_once`: ~9.4 por alerta con pasos (≈14k/día, 101 B, TTL 400 d ≈ 570 MB
  en régimen). Meses y años: decenas de MB al año.

### Retención (O2)

- **Filas de día**: atributo `expires_at` = fecha + 91 días
  (`day_row_expiry`); el planificador nunca las lee pasados 90 días, así que el
  borrado sólo ahorra espacio. **Filas de mes y año**: sin TTL, se conservan
  indefinidamente (la estrategia menciona 24 meses para meses; no está
  implementado, el volumen no lo exige). **Marcadores** (`marker#…`): TTL 400 días.
- El TTL lo activa `ensure_all_tables()` → `enable_ttl(METRICS_ROLLUPS_TABLE,
  "expires_at")` al arrancar el API (también en OKD, con `DYNAMO_ENDPOINT`
  definido); si falla sólo imprime `TTL no aplicado en …`.
- **OKD no corre DynamoDB real**: `storage/db/dynamodb/statefulset.yaml` usa
  `localstack/localstack:3.0` (el README de `iac_celery` aún dice
  dynamodb-local). Verificado: LocalStack 3.0 acepta `UpdateTimeToLive`
  (`DescribeTimeToLive` = `ENABLED`) pero **no borra** ítems vencidos, ni con
  `DELETE /_aws/dynamodb/expired`; DynamoDB Local tampoco. En OKD las filas de
  día y los marcadores crecen sin límite (~1 GB/año a 1.5k alertas/día sobre un
  PVC de 10 Gi). Opciones: versión de LocalStack con borrado de vencidos, un
  job de limpieza por `expires_at`, o DynamoDB real. Las consultas siguen
  correctas en todos los casos.

- **Limpieza compatible con LocalStack/OKD**: Celery Beat ejecuta
  `metrics.cleanup_expired_rollups` diariamente a las 04:00 Bogotá. Borra en
  lotes las filas de día y marcadores con `expires_at <= now`; DynamoDB real
  puede adelantarse mediante TTL. El adaptador usa un `Scan` proyectado sólo a
  claves y vencimiento, así que el coste de lectura crece con el tamaño total
  de `metrics_rollups`; medirlo en OKD antes de fijar el volumen esperado.

### Costo (O3) — modelo on-demand de DynamoDB

Por ítem escrito en una transacción: 2 WCU por KB (redondeado hacia arriba);
la actualización de la alerta además escribe sus 2 GSI con proyección `ALL`
(`EventIdIdx`, `CreatedDayIdx`). Medido re-leyendo una muestra del 3 % de las
transacciones (DynamoDB Local sólo reporta el primer ítem de cada
transacción; LocalStack sí reporta 2 WCU/ítem):

| Evento | ítems por transacción | WCU por evento | eventos por alerta |
| --- | --- | --- | --- |
| CREATED | 4 (alerta + día/mes/año) | 16.5–17.4 | 1 |
| PRE_PROCESSED | 7 (alerta + 3 filas −vieja + 3 +nueva) | 25–27 | 1 |
| WORKFLOW_FINISHED | 7 | 23–29 | 1 |
| ANALYST_RESOLVED / VOICEBOT_COMPLETED | 7 | 20–24 | 0.13 / 0.13 |
| FRAUD_REVIEWED | 4–7 | 18–23 | ~0.32 |
| Paso del workflow (`apply_once`) | 6 (marcador + 3 `workflow_step` + 3 `llm_call`/`research_call` en pasos LLM) | 12.7–14.1 | ~9.4 |

Más una lectura `GetItem` de la alerta por evento (0.5 RRU) y el `PutItem`
de la alerta (4 WCU con sus GSI, no es de métricas).

- **Por alerta**: ~76–87 WRU de la foto + ~125 WRU de métricas técnicas
  ≈ **200–215 WRU** y ~2 RRU.
- **Por día a 1.5k alertas**: ~0.32 M WRU + ~3k RRU. A US$ 0.625 por millón
  de WRU y US$ 0.125 por millón de RRU (on-demand us-east-1; confirmar región)
  ≈ **US$ 0.20/día, ~US$ 6/mes** en escrituras. Almacenamiento (US$ 0.25/GB-mes)
  < US$ 1/mes.
- **Por consulta** (lecturas eventualmente consistentes, 0.5 RRU por 4 KB):
  medido 95 RRU (24 h), 215 (7 d), 480 (30 d), 940 (90 d) con 11k filas; a
  1.5k alertas/día un `/metrics/overview` o `/agent` de 90 días lee ~90k filas
  ≈ 57 MB ≈ **7k RRU** (US$ 0.0009) y `/technical` con 100 % de pasos ~25k
  RRU. Los filtros se aplican en la API después del `Query`: no bajan el costo
  de lectura. Con la caché de 60 s cada combinación de rango+filtros cuesta como
  mucho una lectura por minuto (peor caso: un panel de 90 días abierto todo el
  día ≈ 10 M RRU ≈ US$ 1.3/día).

### Presupuesto de rendimiento (A4)

Medido en proceso (use case real + validación + JSON, sin HTTP/auth) con
`metrics_query_bench`, 12 corridas por caso, 11.5k alertas cargadas
(p95 en ms):

| Endpoint | 24 h | 7 d | 30 d | 90 d sin filtros | 90 d con filtros |
| --- | --- | --- | --- | --- | --- |
| overview | 130–285 | 290–680 | 535–1 600 | 3 230 | 960–1 270 |
| agent | 110–170 | 235–400 | 490–915 | 1 790 | 920–1 060 |
| technical | 130–150 | 300–385 | 600–780 | 1 580 | 1 150–1 220 |
| cualquiera, caché caliente | ≤ 0.5 | ≤ 0.5 | ≤ 1 | ≤ 1.5 | ≤ 1.5 |

- **Sin caché no se cumple** (< 500 ms para 90 d con filtros) ni siquiera con
  ~1/8 del volumen; a 1.5k/día (≈ 8× filas) se extrapola a ~8–10 s en DynamoDB
  Local. En DynamoDB real la parte de red baja (≈ 60 páginas de 1 MB en serie,
  ~2–4 s), pero el plegado en Python (sin filtros ~2 s extra por las
  distribuciones de 11 dimensiones) y la deserialización de boto3 siguen.
- **Caché de 60 s** (`entrypoint/api/metrics_query_cache.py`, conectada en
  `factories/metrics_factory.py`): clave = endpoint + rango ajustado a las
  casillas horarias que lee el planificador + filtros normalizados. Hits
  < 2 ms; el primer acceso (miss) sigue costando lo de la tabla.
- Para cumplir también en frío: consultas por periodo en paralelo, plegar
  `dimension_buckets` en una sola pasada, `ProjectionExpression`, y leer los
  meses completos de más de 4 días desde la fila de mes en vez de 30 filas de día.

## Optimizador del agente (2026-10-26)

Métricas OTLP de baja cardinalidad (nunca ids de sesión, hipótesis o experimento):

| Instrumento | Atributos | Qué responde |
|---|---|---|
| `aria.optimizer.iteration.duration` (histograma, s) | `aria.optimizer.specialist`, `aria.optimizer.outcome` | ¿Cuánto tarda cada especialista y cuánto falla? |
| `aria.optimizer.blocks` (contador) | `aria.optimizer.reason` (código del catálogo) | ¿Por qué se detienen las sesiones esperando al Channel Manager? |
| `aria.optimizer.recoveries` (contador) | `aria.optimizer.reason` | ¿Con qué frecuencia muere un worker a mitad de una iteración? |

Trazabilidad por sesión (no por métrica): la línea de tiempo `agent_events`
(`GET /api/v0/agent/sessions/{id}/events`) correlaciona sesión, iteración,
hipótesis, experimento, verificación y promoción por referencias opacas; los
cambios en producción comparten `audit_correlation_id` con el audit log. Los
spans `agent.session/iteration/specialist/tool` siguen siendo el contrato de
trazas. Alertas sugeridas: `aria_optimizer_recoveries_total` > 0 sostenido (workers
inestables) y `aria_optimizer_blocks_total{reason="COST_ANOMALY"}`.
