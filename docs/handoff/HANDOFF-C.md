# Handoff C — Continuación H5: biblioteca asistida

Fecha: 2026-10-21
Workspace: `backend` (rama compartida; contiene cambios concurrentes de H11)

## Coordinación y límites

La revisión documental del handoff de B confirma el contrato común existente:
paquetes inmutables, verificaciones y confirmaciones append-only. No hay un
agente B activo en este árbol para coordinación en vivo. El vertical reutiliza
esos adaptadores y no añade ni modifica tablas, claves o índices de revisiones.
Se mantuvieron intactos el runner, `AgentExperiment` y la implementación de
auditoría operacional H11. La confirmación usa el `AuditPort` existente.

## Matriz H5

| Entidad de Biblioteca | Estado | Alcance del vertical asistido |
| --- | --- | --- |
| Modus operandi + playbook | Cubierto previamente por H5 | Crear/editar, verificación, diff, procedencia, `base_version`, confirmación auditada y E2E real. |
| Taxonomías | Implementado en C | Crear/editar borrador, preguntas, procedencia por campo, diff, verificadores de esquema/duplicados/PII, control concurrente de `updated_at`, confirmación auditada y aplicación mediante los casos de uso existentes con embedding. |
| Casos similares | Implementado en C | Crear/editar borrador, procedencia, diff, verificación de esquema/duplicados/PII y referencias activas y coherentes; relaciones padre inmutables en edición; control concurrente de `updated_at`; confirmación auditada y aplicación con embedding. |
| Watchlists | Implementado en C | Borrador asistido de metadata, verificadores de esquema/duplicados/PII, diff/procedencia, control concurrente por `updated_at` y confirmación auditada. El CRUD de elementos sigue separado porque se persisten en tabla aparte y pueden ser listas enormes; el agente no los genera ni los cambia. El optimizador conserva su resultado `draft_only` con `live_entity_writes: 0`. |
| Flags | Implementado en C, después de cerrar watchlists | Borrador asistido de tipo, nombre, descripción, variables evolucionadas y vínculos; verificadores de esquema/referencias activas/duplicados/PII, diff/procedencia, CAS por `updated_at` y confirmación auditada. En edición conserva vínculos MO inmutables según el CRUD manual. El optimizador rechaza `entity_type=flag`; no se habilitó ninguna ruta de escritura desde optimización. |
| Otras entradas de Biblioteca | Pendiente de inventario por tipo | Cada tipo requiere su contrato de campos, verificadores y reglas de aplicación antes del vertical asistido. |

## Archivos propios del avance

- `src/application/use_cases/agent/draft_taxonomy.py`
- `src/infrastructure/entrypoint/api/factories/agent_taxonomy_draft_factory.py`
- `src/infrastructure/entrypoint/api/routers/agent_taxonomy_draft_router.py`
- `src/infrastructure/agents/prompts/agent.taxonomy.generate.txt` y su registro en `prompt_seed.py`
- E2E H5 extendido en `scripts/e2e_agent_modus_operandi_local.mjs`
- Pruebas del verificador/diff: `tests/test_application/test_use_cases/test_draft_taxonomy.py`
- Se añadió `expected_updated_at` al puerto, caso de uso y repositorio DynamoDB de taxonomías para impedir la aplicación de borradores obsoletos.
- Casos similares: `src/application/use_cases/agent/draft_similar_case.py`, su prompt, factory y router propios; se reutilizan paquetes, verificaciones y confirmaciones existentes, sin cambio de tablas de revisión.
- Se añadió `expected_updated_at` al puerto, caso de uso y repositorio DynamoDB de casos similares. La edición asistida conserva las referencias al modus operandi y taxonomía padre, según la regla ya aplicada por el endpoint manual.
- Watchlists: `src/application/use_cases/agent/draft_watchlist.py`, su router y factory, prompt dedicado y tests focalizados. El cambio de concurrencia agrega la condición sobre `updated_at` a la escritura existente; no añade tablas ni modifica el esquema compartido de revisiones. Solo se asisten nombre/descripcion/tipo; los elementos siguen en sus rutas de operación.
- Cierre de etapa watchlists (repetido antes de comenzar flags): `make e2e-agent-modus-operandi-local` **pasó** por nginx `http://localhost`. El flujo completo validó creación y edición de watchlist, diff/procedencia y verificadores, rechazo 409 de borrador obsoleto tras un PATCH concurrente, confirmación del borrador renovado y eventos auditados `agent.watchlist.confirmed` / `agent.watchlist.applied`.
- Flags: `src/application/use_cases/agent/draft_flag.py`, su router y factory, prompt dedicado, prueba de CAS del repositorio y pruebas del verificador. El cambio de concurrencia condiciona el `put_item` existente por `updated_at`, sin agregar tablas.
- El E2E H5 extendido ahora cubre ambos verticales: `make e2e-agent-modus-operandi-local` **pasó** por nginx en `http://localhost` con watchlists y flags en creación/edición. En ambos verificó paquete y verificaciones PASS, diff/procedencia, `base_version`, rechazo 409 tras una escritura concurrente y aplicación de la revisión renovada. Comprobó los eventos `agent.watchlist.confirmed` / `agent.watchlist.applied` y `agent.flag.confirmed` / `agent.flag.applied`.
- Protección del optimizador: se probó que los borradores de watchlist se reportan como `draft_only` y `live_entity_writes: 0`, y que un experimento `entity_type=flag` se rechaza como inválido.
- `scripts/e2e_agent_modus_operandi_local.mjs` ahora incluye ambos verticales además de modus operandi: la confirmación de un borrador obsoleto debe responder 409 después de un cambio concurrente y una nueva revisión basada en el estado actualizado debe aplicarse.
- Pruebas del vertical: `tests/test_application/test_use_cases/test_draft_similar_case.py` y ajustes al fake del repositorio existente en `test_similar_case_library.py`.
- Pruebas de watchlists: `tests/test_application/test_use_cases/test_draft_watchlist.py` y ajuste del fake en `test_watchlists.py` para la firma de concurrencia.
- Pruebas flags: `tests/test_application/test_use_cases/test_draft_flag.py`, ajuste de `test_flag_library.py`, test de compare-and-set del adaptador DynamoDB y guard del optimizador en `test_optimizer_specialist_executors.py`.

## Verificación ejecutada

- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest tests/test_application/test_use_cases/test_draft_taxonomy.py tests/test_application/test_use_cases/test_taxonomy_library.py -q`: **7 passed**.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest tests/test_application/test_use_cases/test_draft_similar_case.py tests/test_application/test_use_cases/test_similar_case_library.py -q`: **8 passed**.
- `API_V0_STR=/api/v0 make lint`: **Ruff 0 / mypy 0**, baseline 0.
- `API_V0_STR=/api/v0 make test-architecture`: **244 passed** (repetido tras actualizar las pruebas de suite).
- `node --check scripts/e2e_agent_modus_operandi_local.mjs`: pasó.
- `git diff --check`: pasó.
- `make e2e-agent-modus-operandi-local`: el Playwright real completó por nginx en `http://localhost`; verificó modus operandi, taxonomías y casos similares create/update, verificaciones, diff, versión base, confirmaciones persistidas y eventos auditados. Para casos similares también verificó el rechazo 409 de una edición obsoleta luego de una escritura concurrente, y aplicó un nuevo borrador sobre la versión vigente. Se reconstruyó el contenedor API antes de ejecutar.

- `make e2e-observability`: **1 passed**.
- Última `make e2e-all-local` antes de flags: **25/27 passed**. Fallaron dos escenarios fuera del vertical: E05 agotó 20 minutos esperando que apareciera el modelo `e05-real-1792599919096` en `/modelos`; E03 vector-store recibió 500 al crear su taxonomía fixture (el contexto Playwright no incluye el detalle del servidor). La E2E H5 dedicada posterior a flags pasó con ambos verticales.
- Se corrigió `test_modus_operandi_playbook_defaults_are_independent`: `ShortageBehavior` no tiene `strategy`; ahora el test muta `resolution_tag` y `resolution_method_id` y verifica que los valores por defecto de instancias hermanas no cambian.
- Se corrigió el punto de parcheo de `test_run_classification_exposes_vector_store_research_as_a_bounded_tool`: ahora sustituye `task_factories.get_vector_store_research_tool`, el símbolo consumido por el workflow, y no depende de que `task_factories` se importe después del monkeypatch. Prueba puntual y archivo completo: **8 passed**.
- La causa observada detrás del segundo fallo en la suite amplia es una integración ajena a H5 en el wiring H11 concurrente: `src/infrastructure/workflows/celery/factories.py` pasa `audit=` a `OpenSearchFraudKnowledgeSearchAdapter`, cuyo constructor no acepta ese argumento. El test estabilizado aísla el contrato de `_segment_tool_kwargs`; este cableado de H11 queda caracterizado y pendiente de ese trabajo. No se modificó.
- Corrida completa posterior a corregir ambos tests: **1,481 passed, 8 skipped, 27 warnings**. El proceso terminó con código 0.
- Corrida completa incluyendo los tests del nuevo vertical de watchlists: **1,486 passed, 8 skipped, 27 warnings**.
- Corrida completa tras añadir flags y guard del optimizador: **1,495 passed, 8 skipped, 27 warnings**.
- `make test-architecture`: **246 passed**.
- Verificación tras flags: `make test-architecture` **250 passed**; `make lint` **Ruff 0 / mypy 0**.
- E2E real `make e2e-agent-modus-operandi-local`, a través de nginx en `http://localhost`: modus operandi, taxonomías, casos similares, watchlists y flags create/update. Para ambos verticales confirmó diff/procedencia/verificadores, demostró que una edición manual concurrente hace fallar la confirmación obsoleta con 409, aplicó una edición renovada y comprobó los eventos auditados.
- `mypy --config-file mypy.ini`: **sin errores** después del vertical de watchlists.
- La suite focalizada de watchlists y su vertical: **15 passed**.
- La repetición de `make lint` detectó temporalmente F401/F811 por un import duplicado/unused de `get_agent_audit_repository` en el wiring H11 compartido. Antes de intervenir, el árbol compartido ya contenía el arreglo (un único import local, usado por la composición); `make lint` volvió a pasar con Ruff 0 / mypy 0. No se editó H11 en esta reparación. `git diff --check` y `node --check` pasaron.
- `make test-architecture`: **246 passed**; `make e2e-observability`: **1 passed**.
- Durante esta continuación hubo un fallo transitorio de lint en `fastapi_app.py` por el nuevo import; se ordenó y la verificación final completa quedó limpia.

Watchlists y flags quedan implementados y documentados como verticales H5 separados. Las otras entradas de Biblioteca requieren inventario y alcance propios. No se crearon commits o push.

## H12 — Validación retrospectiva y salida gradual

### Decisiones y contrato

- Contrato para A/FP8 publicado en
  [`HANDOFF-H12-CONTRACT-A.md`](HANDOFF-H12-CONTRACT-A.md) y enlazado desde
  HANDOFF-A. No había canal de mensajería con A disponible; el contrato queda
  compartido en el workspace.
- La etiqueta binaria conserva `evidence_only_v1`: modelo y configuración
  versionados deciden; Biblioteca y Vector Store aportan evidencia. Release v1
  solo permite cambiar el modelo, dado que el router productivo actual no
  puede fijar atómicamente los cuatro componentes.
- SHADOW no cambia el resultado del flujo. Las asignaciones canary usan hash
  estable de `alert_id`; comparaciones se deduplican por release/alerta. Cada
  transición exige 30 observaciones y desacuerdo máximo 5 % bajo la política
  versionada `h12_model_only_v1`.
- El optimizador no solicita aprobación, no avanza etapas ni activa modelos.
  `channel_manager` solicita y envía SHADOW a aprobación; solo `manager` o
  `release_manager` pueden aprobar, avanzar y hacer rollback. No se permite
  autoaprobación.

### Implementación

- `ValidateRetrospectiveReleaseUseCase` recarga las particiones y la colección
  completa del snapshot inmutable, verifica conteos/hash y recalcula scoring
  con objetivo versionado y cuatro pins exactos.
- `ManageAgentReleaseUseCase` controla transiciones, CAS por versión, pila
  previa, pins soportados, slot único de release y guardrails. DynamoDB guarda
  validaciones, releases, observaciones deduplicadas y el slot activo; rollback
  libera el slot y el router deja de seleccionar el candidato.
- `RecordAgentShadowObservation` cuelga del worker de review. En SHADOW compara
  candidato y activo; en canary registra también las comparaciones por etapa,
  sin guardar filas, labels o IDs de alerta en la auditoría.
- `AgentAuditEvent` conserva actor/actor_id, release, versión, snapshot y hash.
  El review worker escribe observaciones con actor `review_worker` e ID de
  servicio `celery:review_worker`. La API de auditoría acepta categoría
  `release` y estados H12.
- El E2E H11 escribe IDs de sesión/experimento en
  `/tmp/aria-h12-h11-result.json`; `make e2e-agent-h12-local` encadena H11+H12
  por nginx. `make e2e-agent-h12-resume-local` reusa esa evidencia sin
  reentrenar. En esta sesión el target compuesto encontró y permitió corregir
  serialización DynamoDB y orden de pins; el recorrido H12 pasó finalmente con
  el target de reanudación sobre el resultado H11 real local.

### Evidencia de stack local — 2026-10-21

- El último H11 usado por el tramo H12 completó seed H8 por nginx (3.000
  elegibles y 262 filas etiquetadas en final). Experimento H11
  `18317eda-e196-45b0-9d0c-6c649981be2e` terminó `SUCCEEDED` local. El target
  `make e2e-agent-h12-resume-local` completó el tramo H12 por nginx con ese
  snapshot.
- Snapshot retrospectivo `4929896f4f3adddcda74816b6b810860`; SHA-256
  `637273f9b745f60ea43f659fd959722beba2f5dc59e2eef8f06916674fb188fc`;
  cuatro pins; validación `PASSED`.
- Release `388ec529-0587-450b-83c3-9c87d352b6e2` bajo
  `h12_model_only_v1`: SHADOW, aprobación de
  `channel_manager` denegada (403), submit con 0 observaciones rechazado
  (409 `GUARDRAIL_NOT_MET`) y rollback de manager `ROLLED_BACK` versión 2.
  Candidato inactivo antes y después.
- La lectura de DynamoDB confirmó release y eventos `RETROSPECTIVE_PASSED`,
  `RELEASE_REQUESTED`, `SHADOW_STARTED` y `ROLLED_BACK`, con actor, versión,
  snapshot y hash.
- Fallos reales corregidos: `created_at` se serializa ISO-8601 para DynamoDB;
  baseline y experimento tenían los mismos pins en orden distinto, por lo que
  la igualdad ahora compara por componente.
- Verificación final: lint Ruff/mypy 0/0; arquitectura 251/251; pytest
  previo focalizado 29/29. Tras hacer explícito `actor_id` del worker,
  la repetición focalizada pasó 6/6; arquitectura 251/251, lint Ruff/mypy 0/0,
  Node syntax checks y `git diff --check` sin errores.
- `make e2e-observability` pasó 1/1 por nginx. `make e2e-all-local` ejecutó
  27 escenarios reales: 25 pasaron y 2 fallaron. E05 intentó activar un modelo
  con el rol de su fixture y recibió 403 `ROLE_NOT_PERMITTED`; E10 esperaba
  `637` en el CSV, pero el reporte real contenía 79 alertas y 278 ejecuciones
  técnicas. No se aisló todavía si son regresiones del contrato de roles ni
  de métricas compartidas; quedan abiertos y no se atribuyen a H12 sin
  reproducción focalizada. El resultado global no es verde.

### Casos no cubiertos y límite

El E2E real cubrió retrospectiva, SHADOW, autorización y rollback antes de
canary. El bucket y la observación canary tienen cobertura unitaria con fake.
El contrato fue cotejado con router, esquemas, casos de uso y hook del worker;
la confirmación corregida está compartida en HANDOFF-A.

Se preparó `make e2e-agent-h12-full-local` y su variante resume. El runner
procesa alertas enviadas por `POST /api/v0/alerts/test`, espera el estado
terminal de cada workflow y consulta agregados persistidos; no inyecta
observaciones. El preflight integrado por nginx detuvo el flujo antes de crear
release o alertas con `H12_E2E_PRECONDITION_XGBOOST_DISABLED`: configuración
activa `default@1`, segmentos `canales_digitales` y `tarjetas` deshabilitados,
`use_xgboost_model=false`, sin `xgboost_model_id`. Por eso no se reúnen 30
observaciones válidas ni se pueden demostrar etapas/rollback posterior a FULL
en este stack. Sin cambiar baseline y crear un H11 nuevo que fije una
configuración con scorer habilitado, ese camino no es alcanzable.

Un probe anterior aceptó `POST /alerts/test` (async operation
`20c96df0-78e2-49ec-b5f0-f305fede0d27`; Celery task
`0a01c4ea-d833-4167-871c-84069bd831a0`), pero nginx devolvió 502 al consultar
el estado mientras Compose reiniciaba el API/worker. No hay resultado terminal
verificable y esa alerta no se contó. El cleanup autenticado posterior informó
`cleaned: []`; no quedó release activo. No se atribuye una observación válida
a ese intento.

H12 permanece abierto hasta correr 30+ observaciones del review worker en cada
etapa, avanzar `CANARY_5 → CANARY_25 → CANARY_50 → FULL` y hacer rollback
después de FULL. Los fixtures locales no son evidencia de despliegue,
promoción productiva ni rendimiento productivo.
