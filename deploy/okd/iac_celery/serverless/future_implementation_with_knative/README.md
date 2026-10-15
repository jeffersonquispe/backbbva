# Plan: migrar workers Celery a Knative

Estado: **propuesta, sin implementar.** Este directorio no gestiona recursos
Knative todavía (no está en `kustomization.yaml`).

Contexto previo: `docs/SCHEDULER_INFRASCRUCTURE.md` ya concluye que Knative
solo es viable alrededor de workers Celery de larga duración si conserva una
réplica mínima caliente y drena con gracia, y que Lambda no encaja. Este plan
desarrolla esa conclusión en pasos concretos.

## 1. Qué significa "reemplazar workers por Knative"

Un worker Celery **jala** mensajes de Redis; Knative Serving **escala servicios
HTTP según requests**. No se puede envolver el proceso `celery worker` en un
Knative Service y esperar que escale: Knative no ve la cola, así que no hay
señal de autoscaling ni scale-to-zero útil.

Hay tres caminos, de menor a mayor cambio:

| Opción | Qué cambia | Scale-to-zero | Esfuerzo | Riesgo |
| --- | --- | --- | --- | --- |
| A. KEDA sobre Celery | `ScaledObject` por Deployment, escala por longitud de lista Redis. El código no cambia | Sí | Bajo | Bajo |
| B. Knative Eventing + Serving | Cada task pasa a ser un handler HTTP que recibe CloudEvents; el broker reemplaza la cola | Sí | Alto | Medio-alto |
| C. Híbrido | B solo para tasks cortas y programadas; Celery se queda para workflows largos, training y simulador | Parcial | Medio | Medio |

**Recomendación:** si el objetivo es *autoscaling y scale-to-zero*, la opción A
lo logra con casi cero cambios de código y debería evaluarse primero (Fase 0).
Si el objetivo es *estandarizar en Knative* (política de plataforma, eventos
CloudEvents, Serverless operator ya disponible), la ruta es C: migrar por
tramos con rollback por feature flag. Este documento detalla B/C.

## 2. Inventario de workloads

Fuente: `src/infrastructure/entrypoint/worker/celery/tasks.py` y
`src/infrastructure/queues/celery/app.py`.

| Task | Disparo | Cola | Candidato Knative |
| --- | --- | --- | --- |
| `workflows.alert_review.run` | API / simulador | `default` | Sí, en fase tardía (larga duración, LLM, autoretry) |
| `workflows.alert_review.escalate_to_analyst`, `document_analyst_decision`, `execute_alert_action` | workflow | `default` | Sí, tras el workflow |
| `metrics.evaluate_alert_reasoning` | workflow | `default` | Sí |
| `async_operations.run` / `reconcile` | API / Beat 60 s | `default` | Sí (reconcile: PingSource) |
| `test_runs.cleanup` | Beat 3600 s | `default` | Sí (PingSource) |
| `metrics.reconcile_alert_rollups` | Beat 02:00 Bogotá | `default` | Sí (PingSource) |
| `object_storage.retention` | Beat 03:00 Bogotá | `default` | Sí (PingSource) |
| `alert_schema.analyze_presence` | Beat 02:30 Bogotá | `default` | Sí (PingSource) |
| `metrics.record_operational_state` | Beat 60 s, `expires` | `default` | Sí, con cuidado: se descarta si no se atiende en su intervalo |
| `datasets.analyze`, `datasets.delete`, `datasets.analyze_fraud_marking` | API | `default` | Sí, medir duración |
| `fraud_review.import_csv`, `analyst_capacity.parse_workbook` | API | `default` | Sí, payload base64 en el mensaje: revisar límite de tamaño del evento |
| `backups.create` | API | `default` | Medir duración; probable Job |
| tasks de CSV test runs | API | `test` | Sí (broker/trigger dedicado, aislado del productivo) |
| `models.train`, `models.preview_features` | API | `model-training` | **No**: imagen pesada (XGBoost/sklearn), `concurrency=1`. Candidato a `Job`, no a Knative Service |
| Tick del simulador | autoprogramado con `countdown` | `event_simulation` (Redis DB 2) | **No** en esta ola: Knative no tiene entrega diferida nativa |
| Celery Beat (scheduler) | proceso único | — | Se reemplaza por PingSources; se elimina el pod |

El MCP y la API ya son servicios HTTP; el MCP puede pasar a Knative Service con
`min-scale: 1` (carga del modelo en memoria), sin cambios de código.

## 3. Por qué la arquitectura lo permite

Los dispatchers viven en `src/infrastructure/queues/celery/*_dispatcher.py` y
`src/infrastructure/workflows/celery/executor.py`; todos llaman
`app.send_task(<nombre>)`. La capa `application/` solo conoce puertos
(`WorkflowExecutor`, `AsyncExecutionInspector`, dispatchers). Por tanto:

- No se toca `application/` ni `domain/`.
- Se agrega un adaptador nuevo bajo `infrastructure/queues/knative/` (o
  `infrastructure/eventing/knative/`) por cada puerto, y se elige con la misma
  variable de entorno que ya existe (`ASYNC_EXECUTOR_BACKEND`, ver
  `async_operation_factory.py`).
- La conmutación por tipo de task permite correr ambos backends en paralelo y
  revertir con un cambio de configmap.

## 4. Diseño objetivo (opciones B/C)

```
API ──CloudEvent──▶ Broker (Kafka) ──Trigger(type=…)──▶ Knative Service (handler HTTP)
PingSource (cron) ─────────────────▶ Broker
                                      └─ DeadLetterSink ──▶ servicio de DLQ / alerta
```

- **Broker:** debe ser durable. El broker in-memory **no** sirve (pierde
  mensajes). Kafka (Strimzi / AMQ Streams) es la opción estándar en OpenShift
  Serverless. Redis no es un canal nativo de Knative Eventing.
- **Handler:** un servicio HTTP mínimo (FastAPI/uvicorn o el SDK de CloudEvents)
  que recibe el evento y llama a las mismas funciones de `tasks.py`. La lógica
  de cada task se extrae a funciones reutilizables por ambos backends para no
  duplicarla.
- **Tipos de evento:** `aria.alert.review.requested`, `aria.dataset.analyze`,
  etc., 1 Trigger por tipo con filtro por `type`.
- **Concurrencia:** `containerConcurrency: 1` para workflows con LLM;
  `max-scale` acotado por el límite de rate del proveedor LLM (hoy el límite
  es `--concurrency=10` en un solo pod).
- **Timeouts:** `timeoutSeconds` de la revisión (y el máximo del cluster
  `max-revision-timeout-seconds`) deben cubrir la task más larga que se migre.
- **Retries/DLQ:** `delivery.retry` + `backoffPolicy: exponential` + `deadLetterSink`
  reemplazan `autoretry_for`/`max_retries`. Los casos que hoy usan
  `dont_autoretry_for` (p. ej. `AdversarialFeedbackLimitExceededError`) deben
  responder 2xx con estado de error de dominio, no 5xx, para que Knative no
  reintente.
- **Idempotencia:** hoy `task_acks_late=True` ya implica entrega *al menos una
  vez*; Knative también. Verificar que cada handler migrado sea idempotente
  (hay marcadores `apply_once` y condicionales en rollups, pero hay que
  revisarlo task por task).
- **Programación (Beat):** `PingSource` con cron. Verificar versión del
  operador para soporte de `timezone` (los crons de 02:00/02:30/03:00 son hora
  de Bogotá, `OPERATIONS_TIMEZONE`). Si no hay soporte, expresarlos en UTC
  (Bogotá es UTC−5, sin horario de verano).
- **Observabilidad:** propagar `traceparent` en los CloudEvents y mantener
  `OTEL_ENDPOINT` como único contrato. Hoy `register_audit_signals()` engancha
  señales de Celery; el handler HTTP necesita su equivalente de auditoría y
  de métricas por task. Las reglas de CLAUDE.md (sin `customer_id` ni monto en
  atributos) siguen aplicando.
- **Secretos y config:** reutilizar `aria-worker-main-config` y
  `aria-worker-main-runtime` mediante `envFrom`/`secretKeyRef`, igual que los
  Deployments actuales. La imagen debe cumplir paridad `Dockerfile.*` local y
  `.okd`.
- **Dependencias:** el proyecto Poetry del worker necesita el servidor HTTP /
  SDK CloudEvents. Mantener fuera XGBoost/sklearn/NumPy/joblib.

## 5. Fases

**Fase 0 — Decisión y mediciones (sin cambios en cluster)**
- Confirmar con plataforma que el operador *OpenShift Serverless* (Knative
  Serving + Eventing) está disponible en el namespace, y qué broker durable
  ofrece. Si no existe, el plan B/C no es viable y se va por A.
- Medir en observabilidad: duración p50/p95/p99 y tamaño de payload por task,
  profundidad de cola y concurrencia efectiva. Esto fija timeouts y decide qué
  tasks quedan en Celery.
- Decidir A vs C con esos datos.

**Fase 1 — Plataforma**
- Manifiestos bajo este directorio: `KnativeServing`/`Eventing` (si los
  gestiona el equipo), `Broker`, `DeadLetterSink`, NetworkPolicies y
  ServiceAccount con `artifactory-auth`.
- Agregar al `kustomization.yaml` solo cuando estén validados en un ambiente.

**Fase 2 — Adaptador y handler (feature flag, backend Celery por defecto)**
- Extraer cuerpos de tasks a funciones compartidas.
- Implementar el adaptador Knative de los puertos y el handler HTTP.
- Tests: fakes en memoria por convención del repo; el adaptador va en
  `tests/test_infrastructure/`. Correr `make lint`, `make test-architecture` y
  `GENAI_ENVIRONMENT=test pytest`.

**Fase 3 — Tareas programadas y de bajo riesgo**
- Migrar `test_runs.cleanup`, `object_storage.retention`,
  `metrics.reconcile_alert_rollups`, `alert_schema.analyze_presence`,
  `async_operations.reconcile` a PingSource + handler.
- Criterio: mismos resultados que Celery Beat durante al menos una semana en
  paralelo, **sin** doble ejecución (apagar la entrada de Beat correspondiente
  al encender la PingSource).

**Fase 4 — Tasks disparadas por API**
- Migrar datasets, importaciones CSV, test runs, backups (o convertirlos en
  `Job`).

**Fase 5 — Workflow de revisión de alertas**
- Es el camino crítico de negocio: migrar al final, con canary (porcentaje del
  tráfico o solo simulador), comparando latencia, tasa de error y consumo de
  tokens contra Celery.

**Fase 6 — Retiro**
- Apagar `aria-worker-scheduler` y workers migrados; mantener Redis solo para
  lo que quede en Celery (training, simulador). Actualizar
  `docs/SCHEDULER_INFRASCRUCTURE.md` y `deploy/okd/iac_celery/README.md`.

## 6. Criterios de aceptación

- Ninguna alerta ni operación se pierde o se procesa dos veces de forma
  visible en el flujo migrado (verificar con conteos de rollups y la
  reconciliación nocturna).
- Latencia p95 de revisión de alerta no peor que la actual (valor de partida
  a medir en Fase 0).
- Rollback completo en un cambio de configmap en cada fase.
- Cold start de los servicios con scale-to-zero medido y aceptado; los que no
  lo toleren quedan con `min-scale ≥ 1`.

## 7. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Timeouts de requests HTTP en tasks largas (LLM, backups) | Medir en Fase 0; dejar en Celery/Job lo que exceda el máximo |
| Cold start en la ruta crítica de alertas | `min-scale: 1` para el handler del workflow |
| Rate limit del proveedor LLM al escalar horizontalmente | `max-scale` y `containerConcurrency` acotados |
| Reintentos duplicados por semántica at-least-once | Revisión de idempotencia por task antes de migrarla |
| Pérdida de tick del simulador | No migrarlo en esta ola |
| Broker no durable o no disponible | Requisito de Fase 0; sin broker durable no se avanza |
| Dos planificadores activos a la vez (Beat + PingSource) | Apagar Beat por entrada al encender la PingSource |

## 8. Preguntas abiertas

1. ¿Está instalado OpenShift Serverless en el cluster de destino y con qué
   versión de Knative?
2. ¿Qué broker durable permite la plataforma (Kafka, otro)?
3. ¿El motivo principal es costo/scale-to-zero (→ A) o estandarización
   (→ C)?
4. ¿Duraciones reales de `workflows.alert_review.run` y `backups.create`?
5. ¿El límite de tamaño de evento del broker admite los payloads base64 de
   los importadores CSV/Excel, o se pasan por object storage y se envía solo
   la referencia?
