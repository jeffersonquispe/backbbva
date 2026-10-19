# Pendientes ARIA

Leyenda: **[V]** verificar · **[I]** implementar · **[D]** diseño/decisión.
La numeración (#n) es la de la lista original.

## 1. Configuración del agente (Rúbricas / Detector) — ✅ hecho 2026-09-28 (sin commit)

- [x] **#1 Rúbricas en el motor** — `_run_rubrics` (tras `profiling`) → puntajes inyectados al prompt del Detector. Aviso quitado. Tests en `test_run_detector.py`.
  - Bug corregido: antes exigía que **todas** las condiciones se cumplieran (0 o todo); ahora es scorecard aditivo (cada condición cumplida suma sus puntos).
- [x] **#2 Normalización a 100** — por rúbrica. Backend: 422 en `CreateConfigurationRequest` (sólo request; versiones viejas siguen legibles). Frontend: total `x / 100 pts` por rúbrica + guardar bloqueado con mensaje.
- [x] **#3 XGBoost en Detector** — ahora el modelo puntúa **antes** del LLM: ≥ umbral fraude o < banda → decide sin LLM; en la banda decide el LLM con el score como evidencia. Sin modelo entrenado → warning + sólo LLM (antes rompía). `shap` añadido a `pyproject.worker.toml`. Bundle cacheado por `storage_ref`. Aviso quitado.
  - Bug corregido: `model_score`/`model_id`/`model_top_features`/`research_delegations` estaban en `ClassifyAlertInput` en vez de `ClassifyAlertOutput` → XGBoost y la investigación delegada del Detector lanzaban `TypeError` en runtime.
  - Pendiente menor: el worker sigue importando `entrypoint/mcp/scoring.py` (podría moverse a un módulo compartido).
- [x] **#4 Pandas → selector de historial** — el selector vive dentro del **Análisis de historial** (sólo aparece al activarlo) y acota los datos que analiza: columnas (`allowed_columns`), ventana en días (`window_days`), máx. transacciones (`max_history_rows`). Operaciones sobre columnas fuera de la selección se omiten (antes fallaba toda la investigación).
- [x] **#6 Herramientas del agente — un solo componente** (`shared/AgentToolsSection.tsx`) idéntico en Detector, Adversarial (detector), Clasificación y Adversarial (clasificador): listas, calculadora, XGBoost, separador **Investigación delegada**, Búsqueda en Vector Store, Análisis de historial. Backend: `AgentToolsConfig` compartido por los 4 configs; cada paso lee su propia copia.
  - **"Base de conocimiento" = Búsqueda en Vector Store** (unificados). El agente lo llama como herramienta (`search_vector_store`) enviando insights, hasta "Máx. interacciones" (`max_delegations`, def. 3); cada intercambio queda en `vector_store_interactions` de la salida del paso. Reemplaza las herramientas directas `get_similar_*`. Configs guardadas con el switch viejo se migran solas al leerlas.
  - **Análisis de historial**: corre si el paso queda inconcluso (Detector/Clasificación) o si el adversarial cuestiona el resultado; luego el paso se reejecuta con los hallazgos (desde #5: hasta "Máx. rondas", tope 5).
  - **XGBoost**: decide sólo en el Detector; en los demás pasos es evidencia. Su salida va **separada** (`model_output`: score, predicción, umbrales, veredicto y `top_features` SHAP) tanto en el prompt como en la salida del paso. SHAP activo por defecto. El score se calcula una vez por alerta y modelo.
  - Analista fuera de alcance (no tiene loop de herramientas); ahora toma el vector store de la Búsqueda en Vector Store de Clasificación.
  - ⚠️ Cambio de comportamiento: los adversariales ya no heredan las herramientas de Clasificación/Detector.
  - Pendiente menor: guardar con la Búsqueda en Vector Store activa y sin instancia no se bloquea en el frontend (el backend responde 422 y la UI muestra el aviso en rojo).

## 2. Orquestación de la investigación delegada — ✅ cerrada 2026-09-28 (sin commit; sólo queda #5b en backlog)

- [x] **#5 Espera Vector Store + Pandas** — documentado + timeout + rondas reales de historial.
  - **Espera**: no hay paralelismo; ambos corren síncronos dentro de la tarea Celery del workflow, en momentos distintos. Vector Store: durante el loop ReAct, cuando el agente llama `search_vector_store`. Historial: después del paso, sólo si queda inconcluso (Detector/Clasificación) o si el adversarial cuestiona.
  - **Relanzamiento**: Vector Store → hasta "Máx. interacciones" llamadas por ejecución del paso. Historial → hasta "Máx. rondas" (`max_delegations`, **tope 5**): análisis → el paso se reejecuta con todos los hallazgos acumulados; se detiene si el paso concluye o si una ronda trae los mismos hallazgos que la anterior. Cada vuelta del loop adversarial → paso crea todo de nuevo (contadores en cero). No hay relanzamiento manual; el autoretry de Celery (3) reejecuta el workflow completo, pero los fallos de la investigación nunca lo disparan.
  - **Fallos**: ambos atrapan su excepción → `FAILED` (el agente lo ve como observación / queda en `research_delegations`), el workflow sigue.
  - **Timeout** (`timeout_seconds`, def. 8 s, 1–60, editable en UI): por consulta de Vector Store y por ronda de historial; si se excede → `FAILED` con `timeout: …`. `TimeBoundedResearchAgent` (hilo aparte; el hilo que se pasa no se puede matar y termina en background, su resultado se descarta).
  - ⚠️ Con el planner heurístico actual (`HeuristicHistoryResearchPlanner`, ignora la pregunta) la ronda 2 siempre repite la 1 → en la práctica se corta tras 1 ronda. Las rondas extra aportan cuando exista un planner LLM que use el razonamiento nuevo → **#5b**.
  - **Fallos del Vector Store no gastan "Máx. interacciones"** (sólo cuentan las respondidas); tras **2 fallos** en el mismo paso la herramienta queda "no disponible" y el agente concluye con lo que tiene.
  - **Renombrado**: ya no se llaman "subagentes" (no lo son: no usan LLM) → **Búsqueda en Vector Store** (herramienta `search_vector_store`, `BoundedResearchTool` en `research_tool.py`) y **Análisis de historial**, en UI, prompts y código.
  - Borrados los campos muertos `max_iterations`, `only_when_inconclusive`, `include_trace` (backend + frontend; configs viejas siguen cargando, la hidratación ignora claves desconocidas).

- [ ] **#5b [I] Planner LLM para el Análisis de historial** — 🔽 **baja prioridad, después de #19** (no bloquea nada; primero medir con lotes CSV si el Análisis de historial aporta con el planner fijo). Mientras tanto, "Máx. rondas" en la UI no tiene efecto práctico (se deja visible). Decisión 2026-09-28: especializar **sin** ReAct anidado (costo ×N por alerta en volumen masivo, auditoría/riesgo de modelo). Hoy el planner es **fijo** (`HeuristicHistoryResearchPlanner`: siempre las mismas 4 operaciones, ignora la pregunta) → las rondas de #5 cortan tras la 1ª.
  - Historial: planner LLM "plan-and-execute" (1 llamada que planea operaciones del lenguaje cerrado; opcional 1 refinamiento con resultados, tope 2), modelo barato, prompt especialista con esquema/columnas. Mismo puerto `HistoryResearchPlanner`, sin código arbitrario. Subir `timeout_seconds` por defecto (~20–30 s) al meter LLM.
  - Vector Store: **sin LLM propio**; en su lugar, parámetros en la herramienta (p.ej. que el agente elija tipo de activo en vez de buscar siempre en los 4).
  - **Medir antes de subir**: mismo lote CSV (con `MARCACION_FIELD`) con planner fijo vs LLM → tasa de inconclusos, acierto vs marcación, latencia, tokens por alerta.

## 3. Estados on/off y recursos — ✅ hecho 2026-09-29 (sin commit)

Decisiones: **nada de esto vive en la config versionada**. On/off, slots de voicebot, matriz de analistas y encolamiento están en el singleton `OperationalSettings` (efecto inmediato + historial), pestaña **"Operación (inmediata)"** con su propio Guardar. El comportamiento ante escasez **no** está en los recursos: lo define el **playbook de cada modus operandi** (Biblioteca). Se eliminaron `OpsSettings`, `AnalystPlaybook` (config) y `FraudPlaybookRecord` (`/library/playbooks`).

- [x] **#7 "Estado del agente"** — cada alerta lleva `origin` (`manual` / `test_run` / `simulator` / `production`; el simulador envía `simulator`). Con OFF, el worker al iniciar salta simulador y producción: workflow `SUCCEEDED` con `output.status="skipped"`, alerta `SKIPPED` y log WARNING (motivo, alert_id, origen). Manuales y lotes CSV se procesan. Verificado en el stack local.
- [x] **#8 "Estado del analista"** — OFF → disponibilidad `0` / `unavailable`; tomar alertas responde `no_capacity` y los playbooks aplican su respaldo.
- [x] **#9 "Estado del voicebot"** — OFF → slots disponibles `0` / `unavailable`; el executor aplica el respaldo del playbook.
- [x] **#12 Slots del voicebot** — cuota fija (`voicebot_max_concurrent_calls`). El executor **reserva** un slot de forma atómica (DynamoDB `TransactWriteItems`, tablas `resource_locks` / `resource_reservations`); `POST /voicebot/callbacks {alert_id, outcome}` lo **libera**. TTL de seguridad **30 min fijo**: vencido, el slot queda libre y la reserva se marca `EXPIRED`. Token opcional `VOICEBOT_CALLBACK_TOKEN` (⚠️ configurarlo fuera de local). Verificado: 40 → 39 → 40.
- [x] **#13 Disponibilidad de analistas** — disponibles = valor de la matriz para la **hora actual** (zona `OPERATIONS_TIMEZONE`, def. Bogotá) − analistas atendiendo una alerta. Cola real en `/cola` + `/alerta/$id` (`/analyst-queue`): tomar reserva 30 min, resolver (bloquear / dejar pasar / bidi + notas) libera y cierra, "Liberar" la devuelve a la cola. 1 alerta por analista (otra → solo lectura, `analyst_busy`), 1 analista por alerta (`alert_taken`); sólo `fraud_analyst` toma y resuelve. Escalar no reserva: se reserva al tomar.
- **Playbook del modus operandi** — estrategia + método principal (analista / voicebot / ARIA) + "si no hay voicebot" + "si no hay analista". El analista (LLM) lo recibe junto con la disponibilidad en vivo; si al ejecutar ya no hay cupo, el executor sigue la cadena sin LLM (un ciclo termina en bloqueo suave). Sin playbook → escala a analista sin LLM → si no hay analista, bloqueo suave.
- ⚠️ Alertas escaladas por fallo del workflow (p. ej. límite adversarial) también entran a la cola (`ESCALATED`).
- Pendiente menor: la pestaña "Alertas en proceso" de `/cola` sigue siendo mock (no era parte de esta sección). "Estados" (montos máx. por canal) se quitó de `/alerta/$id` por no tener fuente de datos.
- Arreglos colaterales: el API no podía encolar alertas (`CeleryWorkflowExecutor` importaba el worker, que trae pandas) → ahora usa `send_task`; el prompt del Analista se perdía al leer la config; `/alerta/$id` era inaccesible para todos los roles (el guard de `DashboardLayout` la redirigía) → ahora cuenta como parte de `/cola`; el `config.cfg` local no tenía `DETECTOR_LLM_MODEL` / `DETECTOR_ADVERSARIAL_LLM_MODEL` / `EXECUTOR_LLM_MODEL` (agregados apuntando a gpt52).
- ⚠️ Entorno local: el deployment de **embeddings** no existe en Azure (crear taxonomías/MO por API da 500 `Resource not found`). Revisar `EMBEDDING_MODEL` en `config.cfg`.
- Verificación: `make test` (744 ✓), `make test-integration-reservations` (DynamoDB local ✓), API + navegador sobre el stack local: Operación (guardar aplica de inmediato + historial), playbook en Biblioteca (guardar, camino, 422), cola (tomar/continuar/resolver/liberar, solo lectura para otro analista), #7 (simulador SKIPPED, manual procesada), #12 (40 → 39 → 40 con callback). Datos QA sembrados: usuarios `ana@`/`beto@` (fraud_analyst) y `qa-manager@aria.local`, taxonomía `qa-tx-ato` y 2 MO `qa-mo-*`.

## 4. Scheduler, retención e infraestructura

- [x] **#10 [V→I] Scheduler** — Celery Beat como servicio `scheduler` independiente, una sola réplica por entorno. Programa reconciliación de operaciones y limpieza de test runs. El tick del simulador se conserva autoagendado.
- [ ] **#11 [V→I] Config software → hardware** — parcial. ✅ Scheduler, limpieza de test runs, configuración operativa y aplicación de capacidad en OKD quedaron implementados. Docker Compose conserva escalado manual; OKD usa KEDA más un reconciliador que aplica `max_instances`, `auto_scale` y `max_test_instances`. Pendiente definir e implementar la retención del historial de fraude (registros/exclusiones legales, almacenamiento frío, verificación/idempotencia del archivo, TTL/índices y retención de backups). En OKD, falta aplicar los prerrequisitos de plataforma: instalar KEDA y configurar Argo CD para ignorar los cambios de réplicas de KEDA.
- [x] **#14 [V] Backend de encolamiento** — Celery 5.6 + Redis, con estado durable de operaciones en DynamoDB.
- [x] **#15 [V→I] Colas por entorno** — pruebas CSV van a `CELERY_TEST_QUEUE` y `test-worker`; producción/manual/simulador va a la cola y worker por defecto. Simulador conserva broker/cola propios.
- [x] **#16 [V/D→I] Escalamiento de pruebas** — KEDA sobre Redis Lists escala independientemente los workers `default` y `test` en OKD; el reconciliador aplica los máximos configurados. Docker Compose mantiene escalado manual. Knative queda como opción futura de capa de despliegue; Lambda descartada para workflows LLM actuales.
- [x] **#17 [D→I] Limpieza de resultados de prueba** — tarea `test_runs.cleanup` cada hora; respeta `manual`/`oldest`/`failed-first`, nunca borra corridas activas y usa cascade idempotente por `run_id`.
- [x] **#18 [D] Alineación de esquemas** — pruebas usan el pipeline y configuración versionada de producción; el contrato de entrada es el esquema crudo del parser. Las diferencias sólo se permiten como overrides explícitos de prompt/modelo.

## 5. Simulación y datos

- [x] **#19 [I] Primera prueba e2e de simulación** — `make test-e2e-simulation` crea un escenario aislado en DynamoDB Local, lo inicia, ejecuta un tick real y verifica su despacho; se limpia al terminar. Frontend: `npm run test:e2e:simulation` recorre el flujo Generador (crear, previsualizar, iniciar y ver estado) con Playwright.
- [x] **#20 [I] Generador de campos por distribución** — constante, categórica ponderada, uniforme, normal, log-normal y Poisson, persistidos y expuestos en el formulario del simulador. La muestra e2e usa sólo campos no personales representativos del CSV local (tipo, canal, integración, scores y monto); el CSV no se carga ni se copia al repositorio.

## 6. UI, observabilidad y otros — #21 ✅ hecho 2026-10-01 (sin commit) · #22 implementado 2026-10-02 (sin commit), faltan Q5/O5

- [x] **#21 Botón de logout** — antes el logout estaba escondido (clic en el avatar) y sólo borraba el token del navegador: el JWT seguía válido hasta su `exp` (1 h).
  - Frontend: botón **Cerrar sesión** (ícono) en el pie del sidebar, también con el sidebar colapsado; el avatar ya no cierra sesión por accidente. Diálogo de confirmación: si el usuario es `fraud_analyst` y tiene una alerta tomada, ofrece **Liberar y cerrar sesión** o **Salir sin liberar** (la reserva vence a los 30 min).
  - Al salir: revoca el token en el backend, borra la caché de React Query y los borradores ligados al usuario (editor de configuración, entrenamiento de modelos, selección de nueva prueba). Las preferencias de UI (pestaña activa, columnas ocultas) se mantienen.
  - Cierre en todas las pestañas a la vez (evento `storage`), y cualquier 401 de la API (token vencido o revocado) manda a `/login?redirect=…`.
  - Backend: `POST /auth/logout` (204) agrega el `jti` del token a la tabla `revoked_tokens` (TTL = `exp`); `get_current_user` rechaza tokens revocados. Los tokens ahora llevan `jti`; los emitidos antes no se pueden revocar y vencen solos en ≤ 1 h. Sólo se cierra **esa** sesión: otras pestañas o equipos con otro login siguen válidos.
  - Arreglo colateral: `/cola` se caía entera ("This page didn't load") cuando una alerta traía `triggeredRules` como texto (`"RULE-1;RULE-2"`, alertas de CSV). Ahora acepta lista o texto.
  - Verificación: 749 tests backend ✓; curl (`/me` 200 → logout 204 → `/me` 401 con el mismo token); Playwright contra el nginx local: ana toma EVT-0001 → Cerrar sesión → diálogo con la alerta → Liberar → las 2 pestañas en `/login`, token y borrador borrados, alerta de vuelta a la cola.
- [x] **#22 [D→I] Dashboards y monitores — base implementada 2026-10-02** (commit `8f0285d`). Se añadieron métricas de negocio/técnicas, agregados DynamoDB, API de dashboards, evaluación de razonamiento, backfill, dashboards Grafana, reglas de alertas, telemetría OTLP y manifiestos del Collector en OKD. El diseño y el plan siguen en `docs/OBSERVABILITY_STRATEGY.md` y `docs/OBSERVABILITY_TASKS.md`.
  - **Decidido 2026-10-01**: KPIs de negocio **y técnicos derivables** en la app desde DynamoDB; agregados día (90 d) / mes / año, todos con perfil por hora 0–23; sólo medidas acumulativas (el frontend lo indica); bucket por fecha de la alerta con deltas a todos los niveles vivos por la maduración del fraude (4 días / 6 meses); `mark` = decisión inmediata e inmutable de ARIA/analista/voicebot; `fraud_` nace igual a `mark` y la corrige el equipo de fraude (lo único tardío); FP y fraude no detectado = `mark` ≠ `fraud_`; timestamps `marked_at` y `fraud_reviewed_at` (cambie o no `fraud_`) para medir el tiempo de maduración; rangos de monto configurables en la config inmediata, congelados por alerta.
  - ✅ **Zona horaria Bogotá en todos los deployments** (hecho 2026-10-01, sin commit): `ENV TZ=America/Bogota` en las 10 imágenes del backend y las 2 del frontend; `TZ` + `OPERATIONS_TIMEZONE` en los configmaps OKD (api, worker, test-worker, scheduler, simulator-worker, mcp), `TZ` en frontend y proxy nginx; Celery con `timezone=OPERATIONS_TIMEZONE` (mensajes siguen en UTC). Verificado: los 7 contenedores locales en `-05`.
  - ✅ **Decisiones M0 cerradas 2026-10-01** (ver `docs/OBSERVABILITY_TASKS.md` → "Decisiones tomadas"): `fraud_label`; subcanal ← `integrationPoint`; `mark` = fraud / no_fraud / pending; sin rangos de monto por defecto; correcciones por UI + CSV; LLM-judge; Collector propio en OKD.
  - ✅ **Implementado 2026-10-02 (sin commit)**: C1–C5, R1–R9, A1–A4 (A4 sólo con caché de 60 s), F1–F6 (frontend_mockup), T1–T6, Q1–Q4, Q6, O2–O4. 971 tests backend ✓, `make test-integration-metrics` ✓, frontend tsc + 18 tests ✓. Runbook: `docs/OBSERVABILITY_RUNBOOK.md`.
  - **Pendiente**:
    - [ ] Q5 E2E Playwright contra el stack local (requiere reconstruir api/worker/web).
    - [x] O5 revisión de código completada; lineamientos en `docs/SECURITY_GUIDELINES_METRICS.md`.
      - [ ] OKD: verificar mínimo privilegio para API/worker y denegar `UpdateItem`/`DeleteItem` sobre `fraud_label_reviews` y `audit_log`.
      - [ ] Negocio/plataforma: definir la retención y confirmar KMS para las notas de fraude y los eventos de auditoría.
      - [ ] Negocio: confirmar el rol autorizado para `fraud_review` (hoy asignado temporalmente a `manager` y `channel_manager`).
    - [ ] A4 en frío no se cumple (90 d ≈ 1 s con 1/8 del volumen; ~8–10 s extrapolado): paralelizar periodos, una sola pasada de distribuciones y `ProjectionExpression`.
    - [ ] TTL no borra en OKD/LocalStack: falta job de limpieza por `expires_at` o validación contra DynamoDB real. También falta cerrar la retención de meses/años.
    - [ ] OKD: sustituir el endpoint upstream placeholder del Collector y definir el valor operativo de `JUDGE_LLM_MODEL`.
    - [x] Código de tablas `metrics_rollups`, `fraud_label_reviews` y `alert_reasoning_evaluations`, GSIs y `make metrics-backfill` ya están implementados; falta provisionarlos/verificarlos en el entorno OKD.
    - [ ] Confirmar palabras de outcome del voicebot, definición de “horario de operación” y catálogo de canal/subcanal crudos para filtros.

## 7. Esquema de alerta y versionamiento

- [ ] **Gobernanza del esquema de alertas** — E1–E17, A1–A5 y E2E automatizados C1–C6 completados; alcance E2E documentado en `docs/ALERT_SCHEMA_E2E_DELEGATION.md`. Para cerrar la puesta en marcha:
  - [ ] **Cargar y activar la v1 en OKD** por Configuración → Esquema: propone `manager`/`release_manager` y aprueba otra persona distinta (B2/D4).
  - [ ] **Verificar en el clúster** la existencia de `alert_schema_versions`, `alert_schema_presence_reports`, `alert_schema_suggestions` y `backups` (D1); bucket, permisos y retención de payload crudo, salida del agente y auditoría del Evento original (D2); y ejecución diaria del análisis de presencia por `aria-worker-scheduler` (D3).
  - [ ] **Verificación manual C1–C6 con la v1 real activa en OKD.** Los E2E automatizados pasan con el esquema de su propio seed y no sustituyen esta comprobación.
  - Referencia para el alcance E2E: `docs/ALERT_SCHEMA_E2E_DELEGATION.md`.

---

**Dependencias:** #10 es base de #11 y #19. #7, #8 y #9 comparten el patrón "estado on/off" → diseñarlos juntos. #12 y #13 comparten el patrón "reserva con expiración".
