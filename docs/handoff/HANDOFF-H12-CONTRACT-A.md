# Contrato H12 para integración con A — 2026-10-21

Estado: cotejado el 2026-10-21 contra el router, esquemas, casos de uso y worker
de review; coincide con el backend salvo las aclaraciones de errores y rollback
incluidas abajo. Compartido en este workspace para FP8. La validación
retrospectiva es síncrona (`PASSED` o error),
usa el snapshot persistido y vuelve a calcular el scoring. No expone estados
intermedios `QUEUED/RUNNING`.

## Flujo

1. Una evaluación retrospectiva vuelve a puntuar un experimento H11 `SUCCEEDED`
   usando su snapshot final inmutable y los cuatro pins. Verifica el hash del CSV
   persistido, vuelve a resolver los pins y reaplica el objetivo versionado. No
   acepta IDs de modelo libres, dataset no autorizado ni hash cliente como
   evidencia.
2. Para la primera salida gradual H12 solo se acepta un cambio de modelo; los
   pins de configuración, Biblioteca y Vector Store deben ser iguales a los del
   baseline. El camino de alertas actual usa un modelo XGBoost configurable y
   todavía no enruta una generación atómica de los cuatro componentes.
   Si supera las restricciones globales y por segmento, `channel_manager` crea
   una solicitud de salida. Comienza `SHADOW`, que compara candidato y stack
   vigente sin cambiar decisiones ni respuestas productivas.
3. `manager` o `release_manager` (persona distinta de quien solicitó) aprueba
   una transición explícita a rollout gradual. El optimizador no puede aprobar,
   avanzar etapas ni activar candidatos.
4. Las etapas son `CANARY_5`, `CANARY_25`, `CANARY_50` y `FULL`. Cada transición
   exige al menos 30 observaciones deduplicadas en la etapa y desacuerdo entre
   candidato y activo no superior al 5 %. La política `h12_model_only_v1` fija
   ese umbral. `expected_version` evita carreras. Rollback detiene el routing
   candidato y libera el slot de release; el baseline nunca se muta en shadow.

## API verificada

- `POST /api/v0/agent/releases/retrospective-validations`
  - Rol: `channel_manager`, `manager` o `release_manager`.
  - Body: `{ "session_id": "<uuid>", "experiment_id": "<uuid>" }`.
  - Respuesta `201`: validation/session/experiment IDs, estado, snapshot/hash,
    pins del candidato y baseline, evidencia, actor y timestamp. Un fallo no
    crea recurso y devuelve error.
- `GET /api/v0/agent/releases/retrospective-validations/{validation_id}`:
  evidencia, snapshot, pins, creador y timestamp.
- `POST /api/v0/agent/releases` (solicitud desde validación `PASSED`): `channel_manager`.
  Body `{validation_id, title, reason}`. Respuesta `201`, estado inicial
  `SHADOW`, incluye stack previo y candidato, autor, revisión y límites.
- `GET /api/v0/agent/releases` y `GET /api/v0/agent/releases/{release_id}`: solo
  `manager`/`release_manager`.
- `POST /api/v0/agent/releases/{release_id}/approve`: solo `manager`/
  `release_manager`; body `{expected_version, reason}`. No permite autoaprobación.
- `POST /api/v0/agent/releases/{release_id}/advance`: solo `manager`/
  `release_manager`; body `{expected_version, target_stage, reason}`. Solo
  permite la etapa inmediata siguiente y requiere guardrails satisfechos.
- `POST /api/v0/agent/releases/{release_id}/submit`: solo `channel_manager`; cierra
  SHADOW y exige guardrails antes de pedir aprobación.
- `POST /api/v0/agent/releases/{release_id}/rollback`: solo `manager`/
  `release_manager`; body `{expected_version, reason}`. Un segundo rollback
  devuelve `409 INVALID_STATE`; no es idempotente. Marca el release como
  terminal y el router deja de seleccionar el candidato; conserva historial
  append-only.

## Estados

- Validación: devuelve `PASSED` si la reevaluación reproducible cumple; si la
  evidencia o restricciones fallan, retorna error y registra
  `RETROSPECTIVE_FAILED`. No persiste un recurso de validación con estado
  `FAILED`.
- Release: `SHADOW → PENDING_APPROVAL → CANARY_5 → CANARY_25 → CANARY_50 → FULL`;
  también terminal `ROLLED_BACK`. El enum contempla `REJECTED` y `FAILED`, pero
  no hay transición API implementada que los emita; se consideran reservados.
- `SHADOW` nunca selecciona el candidato para producir la decisión. La etapa
  `CANARY_*` define una fracción de tráfico reproducible por hash estable del
  ID de alerta, sin exponer el ID en API de métricas ni auditoría.
- Todo cambio incluye `version`, `updated_at`, `actor_id` y `reason`.

## Errores

- `401`: sin autenticación.
- `403 ROLE_NOT_PERMITTED`; autor intentando aprobar su solicitud recibe
  `409 SELF_APPROVAL`.
- `404 EXPERIMENT_NOT_FOUND`, `404 VALIDATION_NOT_FOUND` /
  `404 RELEASE_NOT_FOUND`.
- `409 INVALID_STATE`, `409 VERSION_CONFLICT`, `409 GUARDRAIL_NOT_MET`,
  `409 ACTIVE_STACK_CHANGED`, `409 ACTIVE_RELEASE_EXISTS`,
  `409 UNSUPPORTED_COMPONENT_ROLLOUT`, `409 SELF_APPROVAL`: estado,
  revisión, límites, stack previo o pins no soportados cambiaron.
- `422 EXPERIMENT_NOT_SUCCEEDED`, `422 SNAPSHOT_INVALID`,
  `422 COMPONENT_PIN_INVALID`, `422 VALIDATION_FAILED`,
  `422 OBJECTIVE_NOT_FOUND`: evidencia incompleta, no reproducible, pins u
  objetivo no resolubles o restricciones retrospectivas incumplidas. En el
  `POST` de release, una validación no `PASSED` devuelve `409 VALIDATION_FAILED`;
  un pin candidato no resoluble durante transición devuelve 409.
- Si el scorer shadow falla, el review productivo continúa con el modelo base;
  no se suma observación y el guardrail no deja avanzar. La auditoría de
  desacuerdos no contiene etiquetas ni IDs de alertas.
- Los GET de validaciones y releases son solo para `manager` y
  `release_manager`; la respuesta autorizada del release incluye el agregado
  `observations`.

## Auditoría y seguridad

Eventos append-only: `RETROSPECTIVE_PASSED`, `RETROSPECTIVE_FAILED`,
`SHADOW_STARTED`, `SHADOW_OBSERVATION`, `CANARY_OBSERVATION`,
`SHADOW_COMPLETED`, `RELEASE_REQUESTED`, `RELEASE_APPROVED`,
`ROLLOUT_ADVANCED`, `ROLLED_BACK`. Se guardan actor/actor_id, aprobador, razón,
IDs internos, hash de snapshot, versión y resultado agregado de guardrails.
Nunca se guardan filas, etiquetas individuales o IDs de alertas en auditoría.
Límites iniciales de canary: 5/25/50/100 %, evaluación por
ventana, mínimo de 30 observaciones por etapa y máximo 5 % de desacuerdo. El
scoring shadow no guarda etiquetas ni IDs de alertas. La etiqueta binaria sigue
`evidence_only_v1`; rollout v1 solo acepta cambio de modelo. Cambiar los límites
requiere una nueva versión de política y no puede hacerlo el optimizador.

## Escenario E2E FP8

`make e2e-agent-h12-local` encadena H11 y H12 por nginx, captura el experimento
y snapshot H11, reevalúa retrospectivamente, crea SHADOW, prueba denegación de
aprobación a `channel_manager`, bloqueo sin 30 observaciones y rollback de
`manager`. No inyecta observaciones ficticias. Para recorrer CANARY y FULL, FP8
debe generar al menos 30 observaciones por etapa mediante alertas enviadas a
`POST /api/v0/alerts/test` y procesadas por el Celery review worker. Los
fixtures son sintéticos locales; el resultado no
demuestra despliegue ni rendimiento productivo.

Para recorrer SHADOW + CANARY_5/25/50 + FULL y rollback posterior existe
`make e2e-agent-h12-full-local`; `make e2e-agent-h12-full-resume-local` reusa
el H11 guardado. Antes de emitir alertas el runner exige al menos un segmento
activo con `detector.use_xgboost_model=true` y modelo fijado. El stack local
comprobado no cumple esa precondición (`default@1`: segmentos
`canales_digitales` y `tarjetas` deshabilitados, XGBoost apagado y sin model ID),
por lo que no puede producir observaciones válidas ni se deben inyectar.
