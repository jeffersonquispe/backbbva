# Plan de tareas — métricas, agregados y monitores (#22)

Diseño de referencia: `docs/OBSERVABILITY_STRATEGY.md`. Este documento lo baja a tareas accionables, no sólo funcionalidades: incluye decisiones, contrato de datos, migración, pruebas, operación, seguridad y despliegue.

Formato de cada tarea: **qué** se hace, **dónde** (archivos o capas), **listo cuando** (criterio verificable), **depende de** y **tamaño** (S ≤ ½ día, M ≈ 1–2 días, L ≈ 3–5 días).

---

## Hitos

| Hito | Contenido | Resultado visible |
| --- | --- | --- |
| **M0 Decisiones** | D1–D8 | Contrato de datos cerrado; nada de C/R empieza sin D1, D3 y D8 |
| **M1 Base de datos** | C1–C4, R1–R3, Q1–Q2, Q6 | Cada alerta nueva guarda su foto y suma a los agregados, sin doble conteo |
| **M2 Agregados completos** | R4–R9, Q3–Q4 | Backfill de lo existente, métricas técnicas y reconciliación diaria |
| **M3 API + pantallas** | A1–A4, F1–F3, F5–F6, Q5 | `/dashboard` y `/monitor` sin mocks |
| **M4 Revisión de fraude** | C5, A3, F4 | El equipo de fraude corrige `fraud_` y la maduración se ve en los KPIs |
| **M5 Telemetría** | T1–T6 | Grafana con datos y reglas de alerta; T1 puede arrancar ya, en paralelo |
| **Transversal** | O1–O5 | Runbooks, costos, seguridad, documentación |

Ruta crítica: D1/D3/D8 → C1 → C4 → R3 → R4 → A2 → F2.

---

## 0. Decisiones (M0)

| ID | Decisión | Por qué bloquea | Responsable |
| --- | --- | --- | --- |
| **D1** | Confirmar nombres: `mark`, `fraud_` (¿`fraud_label`?), `marked_at`, `fraud_reviewed_at`, y que una confirmación sin cambio también llena `fraud_reviewed_at` | Son columnas persistidas: renombrar después rompe la hidratación de DynamoDB | Usuario |
| **D2** | Canal de entrada de las revisiones de `fraud_` en producción: API desde el sistema del equipo de fraude, CSV periódico o edición en la UI de ARIA | Define C5, A3 y F4 | Usuario + equipo de fraude |
| **D3** | Rutas del payload para **canal, subcanal y monto** (hoy la UI lee `payload.channel` y `payload.amount.baseValue`; no hay subcanal canónico) | Sin esto no hay dimensiones confiables | Usuario + dueño del contrato del parser |
| **D4** | Orden de fases: recomendado A → C → B → D | Planificación | Usuario |
| **D5** | Collector en OKD: propio en el namespace o corporativo | Sin Collector, T1–T6 no llegan a OKD | Plataforma |
| **D6** | "Alucinaciones" y "Uso correcto de datos": evaluador (LLM-judge muestreado) o se quitan de `/monitor` | Define F3 | Usuario |
| **D7** | Rangos de monto iniciales (¿> 3M / 1M–3M / < 1M?) y su moneda | Valor por defecto de C2 | Usuario |
| **D8** | Tabla de traducción decisión → `mark`. ARIA: `block`, `bidi`, `voicebot`, descarte. Analista: `block`, `pass`, `bidi`. Voicebot: `outcome`. ¿Qué es `bidi`? ¿Y una alerta escalada que nadie resolvió? | `mark` es la base de FP y fraude no detectado | Usuario |

### Decisiones tomadas (2026-10-01)

- **D1**: columnas `mark`, `fraud_label` (no `fraud_`), `marked_at`, `fraud_reviewed_at`. Una confirmación sin cambio también llena `fraud_reviewed_at`. En el resto de este documento, `fraud_` = `fraud_label`.
- **D2**: las correcciones de `fraud_label` llegan por **acción en la UI de ARIA** (`/historico-fraude`) y por **carga CSV masiva** (operación asíncrona). No hay API para un sistema externo en esta ronda (el endpoint existe sólo como respaldo de la UI).
- **D3**: canal ← `channel`; subcanal ← `integrationPoint` / `integrationpoint`; monto ← `amount.baseValue` / `amount_value` (mismos alias que `pre_process_alert.py`).
- **D4**: orden de los hitos M1 → M5.
- **D5**: Collector OTLP propio en el namespace de OKD.
- **D6**: se construye un evaluador LLM-judge muestreado para "Alucinaciones" y "Uso correcto de datos".
- **D7**: sin rangos de monto por defecto (lista vacía → `unknown`).
- **D8**: `mark` tiene **tres valores**: `fraud`, `no_fraud`, `pending`. `block` → `fraud`; `pass` / descarte → `no_fraud`; `bidi` → `pending`; voicebot según su `outcome`; escalada o voicebot sin resolver → `pending`. `pending` se excluye de FP y de fraude no detectado.

---

## 1. Contrato de datos en la alerta (M1, M4)

**C1 — Foto de métricas en la alerta** · M · depende de D1, D3
- Qué: nuevo dataclass `AlertMetricsSnapshot` en `application/ports/alert_port.py`, compuesto en `AlertRecord` como campo opcional (con default, por la regla de herencia de `AlertRecord`). Campos: `origin` (hoy **no se persiste**, sólo vive en `workflow.input`), `segment`, `channel`, `subchannel`, `amount`, `amount_tier`, `amount_tier_set_version`, `configuration_id`, `resolution_method`, `mark`, `fraud_`, `marked_at`, `fraud_reviewed_at`, `fraud_review_count`, `resolution_time_seconds`, `status`, más `snapshot_version` (entero, para idempotencia; ver R3).
- Dónde: puerto, `alert_repository.py` (hidratación **tolerante** a alertas viejas sin el campo), `AlertRepository.update` acepta la foto.
- Listo cuando: una alerta creada antes del cambio se lee sin error; los tests de repo/hidratación cubren alerta vieja y nueva.

**C2 — Rangos de monto configurables** · M · depende de D7
- Qué: `amount_tiers: list[AmountTier(code, label, min_inclusive, max_exclusive)]` + `amount_tier_set_version` en `OperationalSettings`; validación (contiguos, sin solapes, cubren 0 → ∞); cada cambio sube la versión y queda en el historial existente.
- Dónde: `operational_settings_port.py`, schema/request del router, repo DynamoDB, UI en F5.
- Listo cuando: guardar rangos inválidos responde 422; el historial muestra el cambio; las versiones viejas siguen consultables (para etiquetar rangos históricos en A2).

**C3 — Clasificador de monto** · S · depende de C2
- Qué: función pura de dominio `classify_amount(amount, tiers) -> tier_code | "unknown"`.
- Listo cuando: tests de bordes (límite exacto, negativo, `None`, sin rangos).

**C4 — Llenar la foto en cada evento** · L · depende de C1, C3, D8
- Qué: un único use case `RecordAlertMetricsEvent` (orquesta puertos; ver R4) llamado en:
  - creación de la alerta (`alerts_router` / simulador / test runs): `origin`, canal, subcanal, monto, rango congelado, `configuration_id` activo;
  - fin de `pre_process`: `segment`;
  - fin del workflow (`alert_review_workflow.py`, estados `CLOSED`/`ESCALATED`/`FAILED`/`SKIPPED`): `mark` según D8, `resolution_method=aria`, `marked_at`, `resolution_time`; `fraud_` = `mark`;
  - analista resuelve (`resolve_escalated_alert.py`) y callback del voicebot (`complete_voicebot_call.py`): `mark`, `resolution_method`, `marked_at`, `resolution_time`; `fraud_` = `mark`.
- Regla: **ningún otro código** escribe la foto ni los agregados (documentarlo en CLAUDE.md, O4).
- Listo cuando: tests por punto de enganche con fakes en memoria (patrón `Recording...`), verificando la foto resultante.

**C5 — Revisión de `fraud_` por el equipo de fraude** · M–L · depende de D2, C4, R4
- Qué: use case `ReviewFraudLabel(alert_id, fraud_, reviewed_by, note)`: actualiza `fraud_`, `fraud_reviewed_at`, `fraud_review_count` y aplica el delta (R4). Según D2: endpoint `POST /alerts/{id}/fraud-review`, carga CSV masiva (vía operación asíncrona existente) y/o acción en UI.
- Auditoría: tabla append-only `fraud_label_reviews` (quién, cuándo, de → a, nota, canal). Es un dato de negocio de un banco: no se pisa sin rastro.
- Permisos: nuevo permiso (p. ej. `fraud_review`) asignado al rol que defina el usuario.
- Listo cuando: revisar dos veces la misma alerta deja 2 filas de auditoría y los agregados reflejan sólo el último valor; una confirmación (mismo valor) llena `fraud_reviewed_at` sin mover FP.

---

## 2. Agregados (M1, M2)

**R1 — Puerto de agregados** · S
- Qué: `application/ports/metrics_rollup_port.py` (archivo autocontenido): enum `MetricsDataType` (`alert`, `workflow_step`, `llm_call`, `research_call`, `reservation`), enum `RollupLevel` (`day`, `month`, `year`), dataclasses `RollupKey`, `RollupDelta`, `RollupRow`, y `MetricsRollupRepository` (Protocol: `apply(deltas, alert_guard)`, `query(data_type, level, periods, filters)`).
- Listo cuando: el puerto no importa nada de `infrastructure/`.

**R2 — Contribución y delta (funciones puras)** · M · depende de C1
- Qué: `contribution(snapshot) -> (dimensiones, hora_del_día, medidas)` y `diff(old, new) -> list[RollupDelta]` (−vieja, +nueva) para los niveles **vivos** según la fecha de la alerta en Bogotá: día si < 90 días, mes y año siempre.
- Medidas sólo acumulativas: conteos, sumas (monto, tokens), histogramas de rangos fijos (`resolution_time`, maduración: < 1 d, 1–4 d, 4–30 d, 1–6 m, > 6 m), contadores revisadas / cambiadas / confirmadas.
- Listo cuando: tests de bordes de zona horaria (23:30 Bogotá = otro día en UTC), alerta de hace 120 días (sólo mes y año), foto sin cambios (delta vacío).

**R3 — Tabla y escritura exactamente-una-vez** · L · depende de R1, R2
- Qué: tabla `metrics_rollups` (pk `data_type#level#period`, sk = dimensiones serializadas en orden fijo), atributo TTL sólo en filas de día (90 días). La escritura es una **`TransactWriteItems`**: actualizar la foto de la alerta con condición `snapshot_version = esperado` + los `ADD` de los deltas. Un reintento de Celery (autoretry ×3) no puede contar doble.
- Spike previo (S): confirmar que `ADD` sirve para las medidas por hora; si no aplica a rutas anidadas, usar atributos planos `<medida>__h<HH>`.
- Listo cuando: Q2 pasa (reintento simulado no duplica; carrera de dos escrituras → una falla y reintenta con la foto nueva).

**R4 — Writer de métricas** · M · depende de R3
- Qué: use case `RecordAlertMetricsEvent` (usado por C4 y C5): lee foto actual, construye la nueva, calcula `diff`, llama `apply`. Reintento ante conflicto de versión (máx. 3).
- Factories: `@lru_cache` para el repo; use case fresco por llamada; en el worker, en `workflows/celery/factories.py`.

**R5 — Índice por fecha de alerta** · S · depende de C1
- Qué: GSI en `alerts` por `created_day` (Bogotá) para reconciliar, hacer backfill y paginar `/historico-fraude` sin `Scan`.
- Listo cuando: consulta de un día devuelve sólo sus alertas en DynamoDB local.

**R6 — Backfill** · M · depende de R4, R5
- Qué: comando idempotente (`make metrics-backfill FROM=… TO=…`) que reconstruye fotos y agregados de las alertas existentes. Las alertas sin datos suficientes cuentan en dimensiones `unknown`, sin inventar valores.
- Listo cuando: correrlo dos veces deja los mismos números.

**R7 — Reconciliación diaria (red de seguridad)** · M · depende de R5, R6
- Qué: tarea Celery Beat (en `periodic_schedule`, crontab a las 02:00 Bogotá, posible gracias al `timezone` de Celery ya configurado): recalcula días de los últimos 90 y meses de los últimos 6 desde las fotos, compara, corrige y registra cuántas filas difieren (log + métrica `aria.metrics.rollup_drift`, T3).
- Listo cuando: alterar una fila a mano y correr la tarea la deja corregida y reporta drift = 1.

**R8 — Métricas técnicas en la app** · L · depende de R3
- Qué: contribuciones para `workflow_step` (duración, estado, paso, reintentos), `llm_call` (modelo, tokens in/out, latencia, error) y `research_call` (Vector Store / historial: ok / failed / timeout), escritas al terminar cada paso desde los datos que el workflow ya guarda. Dimensiones: las de la alerta + `step_name` / `model`.
- Listo cuando: un workflow de prueba produce las filas esperadas; los tokens sumados coinciden con `test_runs/token_usage.py` para el mismo lote.

**R9 — Contadores en vivo (embudo "Tiempo real")** · S–M
- Qué: entidad separada de los agregados. Primero medir si `list_by_status` usa índice o `Scan`; si escanea, agregar GSI por `status` o contadores `ADD +1/−1` en cada transición.
- Listo cuando: el embudo en vivo responde en < 200 ms con 10k alertas en vuelo (Q3).

---

## 3. API (M3, M4)

**A1 — Planificador de rango** · M · depende de R1
- Qué: función pura `plan(from, to, now) -> lista de (nivel, periodo, horas)`: últimas 24 h = casillas de hoy + ayer; días dentro de 90; meses fuera de 90; mezcla en los bordes. Incluye metadatos de maduración por periodo (< 4 días "en maduración", < 6 meses "puede variar").
- Listo cuando: tests de rangos que cruzan medianoche, fin de mes, fin de año y el límite de 90 días.

**A2 — Endpoints de métricas** · L · depende de A1, R3
- Qué: `GET /metrics/overview`, `GET /metrics/agent`, `GET /metrics/technical` (`from`, `to`, `segment`, `channel`, `subchannel`, `amount_tier`, `status`, `configuration_id`, `resolution_method`). Un use case por endpoint; schemas en `schemas.py`; permisos `dashboard` / `monitor`. La respuesta trae valores, perfil 0–23 h, maduración por periodo y aviso si el rango cruza un cambio de rangos de monto.
- Listo cuando: los números coinciden con un recálculo directo sobre las fotos (Q4).

**A3 — Histórico y revisión** · M · depende de R5, C5
- Qué: `GET /alerts/history` paginado por fecha (GSI de R5) con los mismos filtros, más el endpoint de revisión de C5.

**A4 — Presupuesto de rendimiento** · S · depende de A2, Q3
- Qué: p95 < 500 ms para 90 días con filtros, medido en el stack local con los datos sintéticos de Q3. Si no se cumple: caché corta (60 s) por consulta en el API.

---

## 4. Frontend (M3, M4) — repo `frontend_mockup`

**F1 — Cliente y tipos** · S · depende de A2
- Qué: `src/lib/api/metrics.functions.ts` con los tipos espejo 1:1 de los schemas (regla de contrato del repo).

**F2 — `/dashboard` con datos reales** · L · depende de F1
- Qué: quitar `DEFAULT_FUNNEL`, `DEFAULT_MONTHLY`, `DEFAULT_HOURLY*` y los pesos aleatorios. Indicadores, distribución, perfil horario y embudo en vivo (R9) desde la API. Nota visible: "sólo medidas acumulativas sobre el periodo". Insignias de maduración en FP y fraude no detectado.
- Listo cuando: revisado en el nginx local (`make build && make run`) con datos de Q3.

**F3 — `/monitor` con datos reales** · L · depende de F1, D6
- Qué: indicadores ARIA, analistas y voicebot, técnicos (R8) y % recomendaciones. Alucinaciones y disponibilidad muestran "sin datos" o se quitan según D6.

**F4 — `/historico-fraude` y revisión** · M · depende de A3, D2
- Qué: lista real paginada; si D2 incluye la UI, acción "Revisar fraude" con confirmación y nota.

**F5 — Editor de rangos de monto** · M · depende de C2
- Qué: sección en "Operación (inmediata)" con validación en vivo (contiguos, sin solapes) y aviso de que sólo aplica a alertas nuevas.

**F6 — Filtros desde catálogos** · S · depende de C2
- Qué: segmento y canal desde la Biblioteca (no listas fijas); rangos de monto desde los settings, incluyendo los rangos históricos de versiones anteriores.

---

## 5. Telemetría (M5) — fuera de la app, detrás del Collector

**T1 — Conector `spanmetrics`** · S · sin dependencias (puede arrancar ya)
- Qué: `collector.yaml` local con `spanmetrics` (traces → metrics) y los dashboards `service-overview` / `llm-overview` rehechos sobre esas series, versionados en el repo.
- Listo cuando: con `make observability-up` y una alerta procesada, los paneles muestran datos.

**T2 — Atributos de dimensión en spans** · M · depende de C4
- Qué: mismos nombres que la foto (`aria.segment`, `aria.channel`, `aria.amount_tier`, …) desde un módulo de constantes único. Prohibido en spans: `customer_id` y monto exacto (test que lo verifique). `mark`, `resolution_time` y cada revisión de `fraud_` en spans propios.

**T3 — Métricas OTLP explícitas** · M
- Qué: `MeterProvider` + exportador OTLP en el adapter de monitoring; `gen_ai.client.token.usage`, `gen_ai.client.operation.duration`, `aria.workflow.duration`, `aria.research.calls`, `aria.metrics.rollup_drift`. Sólo dimensiones de baja cardinalidad.

**T4 — Logs por OTLP** · S
- Qué: `LoggingHandler` OTLP con `trace_id` para correlación en Loki.

**T5 — Reglas de alerta como código** · M · depende de T1, T3
- Qué: reglas provisionadas (workflow fallando, LLM caído o lento, SLA en riesgo, cola atascada, sin capacidad, dead man's switch, investigación degradada, drift de agregados > 0 dos días seguidos).
- Listo cuando: cada regla se dispara en local con un escenario forzado (documentado en O1).

**T6 — Collector en OKD** · M · depende de D5
- Qué: manifiestos en `deploy/okd/iac_celery/` (o apuntar al corporativo), `OTEL_ENDPOINT` real en los configmaps y NetworkPolicy de salida.

---

## 6. Calidad (transversal)

| ID | Prueba | Tamaño | Depende de |
| --- | --- | --- | --- |
| **Q1** | Unitarias con fakes en memoria (sin `unittest.mock`): clasificador, `diff`, planificador, writer, revisión | M | C3, R2, A1, R4 |
| **Q2** | Integración contra DynamoDB local (`make test-integration-metrics`, como `test-integration-reservations`): transacción, reintento sin doble conteo, carrera de versiones, TTL presente | M | R3 |
| **Q3** | Carga sintética: 90 días × 1.5k alertas con el simulador → filas por día, latencia de consulta, costo estimado (insumo de A4 y O3) | M | R6 |
| **Q4** | Equivalencia: agregados == recálculo directo desde las fotos, para rangos aleatorios con filtros | S | A2 |
| **Q5** | E2E Playwright: `/dashboard` con filtros y cambio de granularidad contra el stack local | M | F2 |
| **Q6** | Zona horaria: tests de bucket en bordes de día, mes y año en Bogotá | S | R2, A1 |

---

## 7. Operación, seguridad y documentación

| ID | Tarea | Tamaño |
| --- | --- | --- |
| **O1** | Runbook: backfill, reconciliación manual, qué hacer ante drift, cambio de rangos de monto, cómo forzar cada regla de alerta | S |
| **O2** | Retención: confirmar TTL de 90 días en el DynamoDB de OKD (en local no borra; las consultas ya acotan por fecha), y la política de meses y años | S |
| **O3** | Costo: lecturas/escrituras por alerta (≈ 7 ítems por evento) × volumen, con los datos de Q3 | S |
| **O4** | CLAUDE.md: nuevo puerto, regla "sólo `RecordAlertMetricsEvent` escribe agregados", foto en `AlertRecord`, dimensiones prohibidas en spans | S |
| **O5** | Seguridad: permiso de revisión de fraude, auditoría append-only, sin datos personales en agregados ni spans, revisión con `/security-review` antes de M4 | S |
| **O6** | Actualizar `PENDIENTES.md` y `OBSERVABILITY_STRATEGY.md` al cerrar cada hito | S |
