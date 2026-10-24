# HANDOFF — Sesión A

## H12 — contrato API/estados/errores compartido antes de implementación

El contrato para A y FP8 está publicado en
[`HANDOFF-H12-CONTRACT-A.md`](HANDOFF-H12-CONTRACT-A.md). Define validación
retrospectiva sobre experimento H11 y pins inmutables, shadow no influyente,
aprobación humana separada, etapas de canary y rollback, además de roles,
guardrails, errores y un escenario E2E reproducible. La implementación debe
mantener la regla de que el optimizador no activa/promueve candidatos. Este es
un handoff dentro del workspace compartido; no hay un canal de mensajería de A
disponible en esta sesión.

## H0 — Verificaciones previas

Revisión del código en `a5843c74` (rama `feat/agent-A`), sin cambios de
comportamiento.

### Hallazgos H0

1. **Dataset de entrenamiento y madurez.** El caso de uso de inicio valida que
   el modelo esté en borrador y despacha el trabajo, pero no filtra filas por
   madurez (`src/application/use_cases/models/start_model_training.py:44-83`).
   El worker obtiene todas las filas del dataset asociado al modelo
   (`src/infrastructure/workflows/celery/model_training.py:288-301`). No se
   observa un filtro de madurez en ese recorrido. El análisis de marcado de
   datasets sí calcula duración hasta la maduración y actualmente expone
   `p95_days` (`src/application/use_cases/datasets/analyze_fraud_marking.py:186-194`),
   pero es análisis, no un filtro aplicado al entrenamiento.

2. **Compatibilidad con cuatro particiones del catálogo.** El entrenamiento
   lee un solo `model.dataset_name` mediante `get_rows`
   (`src/infrastructure/workflows/celery/model_training.py:288-301`). Después,
   el evaluador divide esas filas internamente en `training`, `validation`,
   `calibration` y `test` (`src/infrastructure/workflows/celery/model_evaluation.py:71-87`).
   Por tanto, el flujo actual no consume sin cambios una referencia a cuatro
   datasets ya particionados: si se le entrega una partición como dataset,
   volverá a subdividirla. La nomenclatura actual también usa `calibration`,
   mientras que Fase S propone `final`.

3. **Rol que aprueba activar una configuración.** En las solicitudes de
   despliegue, `channel_manager` crea la solicitud
   (`src/infrastructure/entrypoint/api/routers/configuration_deploy_requests_router.py:106-120`)
   y la aprobación está restringida a `manager` o `release_manager`; además,
   quien solicitó no puede aprobar su propia solicitud
   (`src/infrastructure/entrypoint/api/routers/configuration_deploy_requests_router.py:145-165`).

4. **Aprovisionamiento de tablas en OKD.** OKD incluye el servicio DynamoDB
   Local bajo `storage/db/dynamodb` en la composición Kustomize
   (`deploy/okd/iac_celery/kustomization.yaml:1-8`); las tablas no tienen
   manifiestos individuales. La API ejecuta `ensure_all_tables()` al iniciar
   cuando `DYNAMO_ENDPOINT` está configurado
   (`src/infrastructure/entrypoint/api/initialization/tables.py:17-29`,
   `src/infrastructure/entrypoint/api/fastapi_app.py:116-128`), y `manager.py`
   declara el conjunto de tablas existentes (`src/infrastructure/persistence/database/dynamodb/manager.py:361-420`).
   Esto documenta aprovisionamiento dinámico por la aplicación, pero no prueba
   que Argo CD haya sincronizado los recursos ni que las tablas estén creadas
   en un clúster OKD concreto. Para confirmarlo se necesita inspección del
   clúster. Las tablas nuevas de la propuesta todavía no están en el código
   base revisado.

### Estado de H0

- **Qué quedó hecho:** las cuatro preguntas de código quedaron verificadas y
  documentadas arriba.
- **Archivos tocados:** `docs/handoff/HANDOFF-A.md` únicamente.
- **Comandos ejecutados:** lectura de `CLAUDE.md`, secciones requeridas del
  backlog y guías del frontend; búsquedas `rg` y lecturas `nl -ba` de los
  archivos citados. Sin pruebas, porque H0 no construye ni cambia comportamiento.
- **E2E:** no aplica a H0, que es una verificación sin construcción.
- **Supuestos nuevos:** no se infiere el estado vivo del clúster desde los
  manifiestos del repositorio.
- **Pendiente del integrador:** aprobar H0 antes de iniciar H1, según el flujo
  de hitos acordado. No iniciar H6 hasta recibir luz verde explícita después
  de que H1 y H2 estén mergeados.

## H1 — Ventana de maduración configurable

### Qué quedó hecho

- `OperationalSettings` expone `maturing_days` (4),
  `expected_coverage_pct` (98.0) y `stable_months` (6). La API valida los
  rangos en servidor; la actualización registra el diff y su autor en el
  historial. El endpoint de escritura permite `manager` y `release_manager`.
- `range_planner` usa parámetros configurables en lugar de
  `MATURING_DAYS`/`MAY_VARY_MONTHS`. Los lectores de métricas obtienen los
  ajustes actuales y se invalida la caché de métricas al guardarlos.
- El análisis de marcado incluye p50, p75, p90, p95, p98 y p99. El panel de
  Operación permite editar y guardar los tres ajustes; el resumen de dataset
  muestra esos percentiles.
- Se agregó E2E real que inicia sesión por API, opera la UI en nginx, verifica
  persistencia e historial, y restaura los valores originales.

### Archivos tocados

Backend: `src/application/ports/operational_settings_port.py`,
`src/application/use_cases/operational_settings/update_operational_settings.py`,
`src/application/use_cases/metrics/{range_planner,alert_metrics_reader,get_agent_metrics,get_metrics_overview,get_technical_metrics}.py`,
`src/application/use_cases/datasets/analyze_fraud_marking.py`,
`src/application/dtos/dataset_dtos.py`,
`src/infrastructure/entrypoint/api/{factories/metrics_factory.py,routers/operational_settings_router.py,schemas/datasets.py,schemas/operational_settings.py}`,
`src/infrastructure/persistence/database/dynamodb/repositories/operational_settings_repository.py`
y las pruebas correspondientes en `tests/test_application` y
`tests/test_infrastructure` para ajustes, métricas, análisis, API y DynamoDB.
Este handoff también se actualiza.

Frontend (árbol `../frontend_mockup`):
`src/lib/api/operations.functions.ts`,
`src/components/configuracion/OperationsPanel.tsx`,
`src/lib/api/datasets.functions.ts`,
`src/components/datasets/DatasetSummaryTab.tsx` y
`e2e/operational-settings-real.spec.ts`.

### Verificación

- `RUFF_CACHE_DIR=/private/tmp/aria-h1-ruff make lint`: pasó; Ruff 0 errores,
  mypy 102 errores con baseline 102 (sin crecimiento).
- `API_V0_STR=/api/v0 make test-architecture`: 214 pasaron.
- `GENAI_ENVIRONMENT=test API_V0_STR=/api/v0 pytest -p no:cacheprovider` con
  los siete módulos tocados de ajustes, planner, análisis, repositorio, router
  y métricas: 65 pasaron.
- `git diff --check`: pasó.
- `npx eslint` sobre los cuatro módulos frontend y el spec E2E: pasó.
  `npx tsc --noEmit`: pasó. El `npm run lint` completo del mockup falla por
  1297 errores Prettier existentes y archivos generados bajo `docs/assets`; el
  lint focalizado de estos cambios sí pasa.
- `make e2e-all-local` (suite completa real por `http://localhost`): 16 pasaron,
  3 omitidos y 4 fallaron en flujos preexistentes (raw-access-audit 404,
  despliegue de configuración 500 y fixture de entidades 500). En esa primera
  ejecución la imagen API no contenía aún los cambios H1, por lo que la prueba
  nueva también falló. Tras reconstruir el stack y corregir el helper para
  sembrar el token antes de iniciar la app, `E2E_TEST_FILES=e2e/operational-settings-real.spec.ts
  make e2e-all-local`: 1 pasó por nginx, sin mocks de API. El lock
  `/tmp/aria-e2e.lock` se liberó al terminar.

### Supuestos y pendientes

- Como la guía no fijaba límites numéricos, servidor y UI aceptan
  `maturing_days` de 0 a 365, `expected_coverage_pct` mayor que 0 y hasta 100,
  y `stable_months` de 0 a 120. Se eligieron percentiles p50/p75/p90/p95/p98/p99
  para conservar p95 y dar contexto alrededor de la cobertura objetivo 98%.
- Se atribuye el cambio al correo del usuario autenticado; el cliente no
  determina el autor.
- **Estado:** implementación H1 completa y E2E focalizado pasado; pendiente de
  revisión/aprobación del integrador. No iniciar H2 ni H6 antes de esa
  aprobación; H6 requiere además H1 y H2 mergeados y luz verde explícita.
- **Necesito del integrador:** revisar y aprobar H1 para merge. El contrato de
  `assistant_optimizer_settings_port.py` no se modificó ni se adelantó trabajo
  H2. No se requiere una acción de B para esta entrega.

### Revisión del integrador — corrección de autenticación

- En `tests/test_infrastructure/test_entrypoint/test_reasoning_evaluation_settings.py`,
  el cliente de prueba ahora inyecta un usuario `manager` válido mediante
  `get_current_user`. La petición fuera de rango alcanza la validación y
  devuelve 422; el valor cero sigue aceptándose con 200.
- Verificaciones repetidas tras la corrección:
  `RUFF_CACHE_DIR=/private/tmp/aria-h1-ruff make lint` pasó (Ruff 0 errores,
  mypy 102 con baseline 102); `API_V0_STR=/api/v0 make test-architecture`
  pasó (214); el pytest focalizado de los ocho módulos H1 pasó (67, 2 warnings).
  El módulo corregido por separado también pasó (2). `git diff --check` pasó.
- No se reprodujo otra falla en el pytest focalizado. Según lo indicado por el
  integrador, la falla observada en la ejecución previa ya existía en
  `fc8973a`; no se atribuye a H1.
- **Estado:** H1 sigue completo. Lint, arquitectura y pytest focalizado están
  verdes. A queda autorizado para iniciar H2 según la aprobación explícita del
  integrador; H6 continúa esperando que H1 y H2 estén mergeados y luz verde.

## H2 — Configuración del asistente y el optimizador

### Qué quedó hecho

- Añadido el puerto de settings del integrador sin cambios en sus campos ni
  defaults. `AssistantOptimizerSettings` conserva las propiedades de
  maduración del contrato, pero el repositorio H2 no las persiste: son
  propiedad de `OperationalSettings`.
- Añadidos el adaptador DynamoDB del singleton y el historial append-only, con
  tabla de cambios indexada por `record_id` y `changed_at`. El caso de uso
  calcula el diff; registra autor/hora y escribe la auditoría usando `AuditPort`.
- API `GET/PUT /api/v0/assistant-optimizer-settings` y
  `GET /api/v0/assistant-optimizer-settings/changes`. Todas requieren usuario
  `manager` o `release_manager`; el autor proviene del usuario autenticado.
  Se validan límites numéricos, política de semilla, listas y suma de las tres
  proporciones de partición (train + validation + test = 1).
- Las tablas se incluyen en `schemas.py` (el respaldo enumera dinámicamente
  todas las tablas declaradas ahí), `manager.ensure_all_tables()` y la limpieza
  E2E. En OKD no hay manifiestos individuales de tablas DynamoDB: el mismo
  aprovisionamiento dinámico al iniciar la API cubre DynamoDB Local.
- Añadida la pestaña “Asistente y optimizador” a manager y release manager, con
  el componente independiente `AgentSettingsPanel`, guardado por sección,
  historial, restauración de defaults, controles de límites y confirmación
  explicada al apagar interruptores/subir topes. La pestaña no aparece para
  `channel_manager`.
- E2E Playwright real con nginx que guarda desde la UI, confirma la persistencia
  y autor en historial y restaura la configuración previa.

### Archivos tocados

H2 backend: `src/application/ports/assistant_optimizer_settings_port.py`
(copiado sin modificación del contrato en `../backend`),
`src/application/ports/assistant_optimizer_settings_changes_port.py`,
`src/application/use_cases/assistant_optimizer_settings.py`,
`src/infrastructure/persistence/database/dynamodb/repositories/assistant_optimizer_settings_repository.py`,
`src/infrastructure/persistence/database/dynamodb/{schemas.py,manager.py,repositories/e2e_state_cleaner.py}`,
`src/infrastructure/entrypoint/api/{fastapi_app.py,factories/assistant_optimizer_settings_factory.py,routers/assistant_optimizer_settings_router.py,schemas/assistant_optimizer_settings.py}`
y pruebas nuevas bajo `tests/test_application` y `tests/test_infrastructure`.
H1 continúa sin commit en la misma rama de trabajo.

Frontend (`../frontend_mockup`):
`src/lib/api/assistantOptimizerSettings.functions.ts`,
`src/components/configuracion/AgentSettingsPanel.tsx`,
`src/data/configs.ts`, `src/routes/configuracion.tsx` y
`e2e/assistant-optimizer-settings-real.spec.ts`.

### Comandos ejecutados y resultados

- `RUFF_CACHE_DIR=/private/tmp/aria-h2-ruff make lint`: pasó; Ruff 0 errores,
  mypy 102 errores con baseline 102.
- `API_V0_STR=/api/v0 make test-architecture`: 217 pasaron; dos avisos del
  pytest cache por no poder escribir `.pytest_cache` en el worktree.
- `GENAI_ENVIRONMENT=test API_V0_STR=/api/v0 pytest -p no:cacheprovider` con
  pruebas de H1, puerto H2, caso de uso H2, repositorio H2, limpiador E2E y
  router H2: 87 pasaron, 2 warnings ya identificados (colección de
  `TestCleanupPolicy` y deprecación Starlette).
- `npx eslint src/lib/api/assistantOptimizerSettings.functions.ts src/components/configuracion/AgentSettingsPanel.tsx src/data/configs.ts e2e/assistant-optimizer-settings-real.spec.ts`:
  pasó. `npx tsc --noEmit`: pasó.
- `npx eslint src/routes/configuracion.tsx`: falla con 339 errores Prettier
  distribuidos por el archivo de ruta de 2.700+ líneas; no se autoformateó ese
  archivo. La compilación TypeScript y el E2E real confirman que la pestaña
  añadida funciona.
- `E2E_TEST_FILES=e2e/assistant-optimizer-settings-real.spec.ts make e2e-all-local`:
  primer intento sandbox bloqueado al escribir
  `~/.docker/buildx/activity/.tmp-default...` (`operation not permitted`);
  repetido con permiso para Docker, pasó 1/1 por `http://localhost`.
  Repetido tras el ajuste final del panel, pasó 1/1 otra vez. No se usaron
  mocks de API. `/tmp/aria-e2e.lock` fue liberado al terminar.
- `git diff --check`: pasó.

### Supuestos, discrepancias y estado

- Los rangos concretos de los parámetros sin límites establecidos en la guía
  son los que valida `_validate` en el caso de uso y presenta la UI. La guía sí
  fija 8.000 caracteres por mensaje y 730 días de retención; esos topes quedan
  aplicados. Las proporciones de partición se limitan a valores positivos que
  suman 1.
- La versión del puerto en `../aria-wt-B` tiene defaults distintos para el
  tope monetario/duración y no incluye `optimizer_stop_on_critical_failure`.
  La implementación A copió literalmente la versión del contrato ubicada en
  `../backend`; el integrador debe reconciliar esa divergencia entre worktrees.
- La guía requiere historial/diff/auditoría, mientras el contrato del puerto
  entregado declara solamente `get/update`. Para no alterar el contrato, A
  agregó `AssistantOptimizerSettingsChangesPort` para la entidad separada de
  historial y mantuvo los cambios al settings port en cero.
- **Estado:** H2 implementado y checks backend verdes; E2E real pasó. Pendiente
  de revisión e integración. No iniciar H6 hasta que H2 se integre y el usuario
  dé luz verde explícita.
- **Necesito del integrador:** reconciliar la diferencia del puerto entre
  `../backend` y `../aria-wt-B`, revisar H2 y resolver los cambios H1/H2 al
  integrar. No se requiere trabajo de B en sus zonas reservadas.

## H6 — Muestreo de datos maduros (implementado, pendiente de revisión)

Base: `83326e2` (incluye H3 integrado en `37e5df4`), rama `feat/agent-A-h6`,
worktree `../aria-wt-A-h6`. Se recibió luz verde para H6 con prioridad sobre
FP0/FP1.

### Qué quedó hecho

- Muestreo reproducible y estratificado. Solo entran alertas con etiqueta final
  (`fraud`/`no_fraud`) y edad suficiente según `OperationalSettings.maturing_days`.
- **Los campos de estratificación, etiqueta objetivo y fecha de marcación los
  elige el manager desde el pool del esquema**. La etiqueta seleccionada se
  mapea a las clases canónicas `fraud`/`no_fraud`; el servidor usa esa etiqueta
  y fecha para elegibilidad, vista previa, disparadores y materialización. No
  consulta los campos fijos de métricas internas para decidir la madurez. El
  campo de salida `fraud_label` sigue siendo el nombre canónico requerido por
  el trainer, y `__aria_partition` es metadato técnico del dataset conjunto.
  `GET .../sampler/schema-configuration` publica los pools compatibles y
  `PUT` valida y audita la selección. `GET .../sampler/fields` obtiene los
  campos de estratificación de versiones activa/compatibles y filtra sensibles
  y etiquetas. Las filas materializadas usan los campos elegidos, sin nombres
  de columnas de negocio codificados.
- Se materializan cuatro CSV de catálogo (`training`, `validation`, `test`,
  `final`) y un quinto dataset conjunto para que el trainer lea una sola
  referencia y respete las particiones sin volverlas a dividir. Los snapshots
  conservan especificación, periodo, madurez, versiones de esquema, conteos,
  hash SHA-256, disparador y referencias a datasets; el estado guarda último
  snapshot y conteos. Hay idempotencia y retención configurable.
- API de vista previa, pool de campos y ejecución manual; permisos limitados a
  `manager`/`release_manager`. Celery procesa `async_operations`, y Beat evalúa
  disparadores periódico, por volumen y PSI estadístico con enfriamiento.
- `model_evaluation` conserva las cuatro particiones, mapeando `test` del
  muestreador a `calibration` del entrenador y `final` a su prueba final; quita
  el marcador técnico de las features.
- Las tablas nuevas están en `schemas.py` y `manager.py`; también en limpieza
  E2E. El respaldo enumera dinámicamente las tablas de `schemas.py`; OKD usa
  aprovisionamiento al iniciar API, igual que el resto de tablas.
- `AgentSettingsPanel` ofrece selección por checkboxes desde esquema, vista
  previa agregada y botón para ejecutar. El primer E2E detectó que
  `sampler_strata` no se incluía en las claves guardadas por sección; se corrigió
  y se repitió E2E con éxito.

### Archivos tocados

Backend: `src/domain/datasets/{mature_sampling.py,mature_sample_entities.py}`,
`src/application/dtos/mature_sample_dtos.py`,
`src/application/ports/{dataset_sampler_state_port.py,dataset_snapshot_port.py}`,
`src/application/use_cases/datasets/{preview_mature_sample.py,create_mature_sample_snapshot.py}`,
`src/infrastructure/entrypoint/api/{factories/assistant_optimizer_settings_factory.py,routers/assistant_optimizer_settings_router.py,schemas/assistant_optimizer_settings.py}`,
`src/infrastructure/entrypoint/worker/celery/tasks.py`,
`src/infrastructure/persistence/database/dynamodb/{schemas.py,manager.py,repositories/mature_sample_repository.py,repositories/e2e_state_cleaner.py}`,
`src/infrastructure/queues/celery/{app.py,mature_sample_executor.py}`,
`src/infrastructure/workflows/celery/{task_factories.py,model_evaluation.py}` y
pruebas nuevas/actualizadas para dominio, casos de uso, API, worker, limpieza y
entrenamiento.

Frontend (`../frontend_mockup`):
`src/lib/api/assistantOptimizerSettings.functions.ts`,
`src/components/configuracion/AgentSettingsPanel.tsx` y
`e2e/mature-sampler-real.spec.ts`.

### Comandos ejecutados y resultados reales

- `RUFF_CACHE_DIR=/private/tmp/aria-h6-ruff make lint`: **pasó**, Ruff 0,
  mypy 0, baseline sin crecimiento.
- `API_V0_STR=/api/v0 make test-architecture`: **pasó**, 227 pruebas; warning
  conocido de pytest al no poder escribir `.pytest_cache` en el worktree.
- `GENAI_ENVIRONMENT=test API_V0_STR=/api/v0 pytest -p no:cacheprovider tests/test_domain/test_mature_sampling.py tests/test_application/test_use_cases/test_preview_mature_sample.py tests/test_application/test_use_cases/test_create_mature_sample_snapshot.py tests/test_infrastructure/test_entrypoint/test_assistant_optimizer_settings_router.py tests/test_infrastructure/test_persistence/test_e2e_state_cleaner.py tests/test_infrastructure/test_entrypoint/test_worker_celery_app.py tests/test_infrastructure/test_workflows/test_model_training.py`:
  **24 pasaron**, una deprecación de Starlette.
- En `../frontend_mockup`:
  `npx eslint src/lib/api/assistantOptimizerSettings.functions.ts src/components/configuracion/AgentSettingsPanel.tsx e2e/mature-sampler-real.spec.ts`
  y `npx tsc --noEmit`: **pasaron**.
- `git diff --check`: **pasó**, incluida esta actualización del handoff.
- `E2E_TEST_FILES=e2e/mature-sampler-real.spec.ts make e2e-all-local`, con lock
  `/tmp/aria-e2e.lock`, reconstruyó la API/workers/web y se ejecutó a través de
  nginx `http://localhost:80`, sin mocks. Primera ejecución: falló porque el
  guardado de sección omitía `sampler_strata`. Tras corregirlo, la repetición
  pasó **1/1**. La prueba crea una alerta y la etiqueta vía API real, valida el
  pool de esquema, guarda desde la UI, ejecuta el muestreo, consulta
  `async_operations` y comprueba hash y referencias/conteos de las cuatro
  particiones. El lock se liberó en ambas ejecuciones.

### Supuestos y estado

- La API toma fecha de referencia del reloj UTC del worker. La selección fija
  por periodo produce ID estable; para `random_per_sample`, el seed varía al
  crear por primera vez el snapshot.
- El contrato solo tiene una proporción de holdout. Se divide en partes iguales
  entre `test` y `final`; así quedan cuatro particiones y se conserva la suma
  configurada de training/validation/test. Confirmar si el producto requiere
  parámetros separados para calibración y evaluación.
- Se usa un dataset conjunto con marcador interno más los cuatro CSV separados
  porque el trainer H0 consume un `dataset_name`; con ese marcador evita el
  re-split y conoce las cuatro particiones.
- El E2E previo falló después de cambiar `maturing_days` a cero y antes de
  alcanzar su `finally`; se restauró manualmente el valor previo conocido (4)
  en DynamoDB Local. El E2E repetido restaura valores en `finally`.
- **Estado:** implementación H6 completa, lint/arquitectura/pytest y E2E real
  verdes tras la corrección; pendiente de revisión del integrador. No iniciar
  BS.1–BS.8 ni otro hito sin aprobación. FP0/FP1 queda cubierto en esta entrega
  por el panel y el spec de interacción del muestreador.
- **Necesito del integrador:** revisar H6 e integrar la rama. No se requiere
  intervención de B.

### Ajuste H6 antes de integración — marcas y fechas desde el esquema

- **Qué quedó hecho:** el manager selecciona del esquema los cuatro campos:
  marca inicial, fecha inicial, etiqueta vigente y fecha de última marcación.
  Los pools admiten campos de marca compatibles y fechas `date`/`datetime`;
  se excluyen campos sensibles. El servidor valida pertenencia y tipos,
  requiere fechas distintas, exige un mapeo fuente explícito para `fraud` y
  `no_fraud`, y registra diff/historial/auditoría. Preview y snapshots leen la
  etiqueta vigente desde `AlertRecord.labels` y la fecha de última marcación
  desde el campo de entrada elegido; los snapshots también materializan los
  campos seleccionados de marca inicial y fecha inicial con sus nombres de
  esquema. Se agregó una prueba que simula renombres del esquema, expone las
  nuevas opciones y rechaza los nombres obsoletos. El mapeo vive como fila
  `schema_mapping` de la tabla ya existente
  `dataset_sampler_state`: no se añade tabla ni se cambia el contrato del
  integrador `assistant_optimizer_settings_port.py`.
- **Archivos backend tocados:**
  `src/application/ports/mature_sampler_schema_mapping_port.py`,
  `src/application/use_cases/datasets/configure_mature_sampler_schema.py`,
  `src/domain/datasets/mature_sample_entities.py`,
  `src/domain/datasets/mature_sampling.py`,
  `src/application/use_cases/datasets/{preview_mature_sample.py,create_mature_sample_snapshot.py}`,
  `src/infrastructure/persistence/database/dynamodb/repositories/mature_sample_repository.py`,
  `src/infrastructure/entrypoint/api/{factories/assistant_optimizer_settings_factory.py,routers/assistant_optimizer_settings_router.py,schemas/assistant_optimizer_settings.py}`,
  `src/infrastructure/workflows/celery/task_factories.py` y pruebas de los
  casos de uso, dominio y router indicadas abajo.
- **Archivos frontend tocados:**
  `../frontend_mockup/src/lib/api/assistantOptimizerSettings.functions.ts`,
  `../frontend_mockup/src/components/configuracion/AgentSettingsPanel.tsx` y
  `../frontend_mockup/e2e/mature-sampler-real.spec.ts`, más el montaje de la
  pestaña en `../frontend_mockup/src/routes/configuracion.tsx` y su clave en
  `../frontend_mockup/src/data/configs.ts`.
- **Comandos y resultados reales:**
  `RUFF_CACHE_DIR=/private/tmp/aria-h6-adjustment-ruff make lint`: pasó,
  Ruff 0 y mypy 0, baseline sin crecimiento.
  `API_V0_STR=/api/v0 make test-architecture`: 229 pasaron; warning conocido
  porque pytest no puede crear `.pytest_cache` en el worktree.
  `GENAI_ENVIRONMENT=test API_V0_STR=/api/v0 pytest -p no:cacheprovider
  tests/test_domain/test_mature_sampling.py
  tests/test_application/test_use_cases/test_configure_mature_sampler_schema.py
  tests/test_application/test_use_cases/test_preview_mature_sample.py
  tests/test_application/test_use_cases/test_create_mature_sample_snapshot.py
  tests/test_infrastructure/test_entrypoint/test_assistant_optimizer_settings_router.py`:
  20 pasaron, 1 warning de deprecación Starlette.
  En `../frontend_mockup`, `npx eslint --fix` sobre API, componente y E2E,
  `npx eslint` focalizado y `npx tsc --noEmit`: pasaron. La pestaña expone
  selectores para los cuatro campos y el spec obtiene las opciones de la API,
  sin fijar nombres de columnas.
  `E2E_TEST_FILES=e2e/mature-sampler-real.spec.ts make e2e-all-local`, con
  lock `/tmp/aria-e2e.lock`: reconstruyó API/workers y frontend nginx; el
  Playwright real por `http://localhost:80` pasó 1/1, sin mocks de API. El
  test selecciona los cuatro campos desde las opciones reales de la API,
  configura el mapeo, crea y revisa una alerta,
  ejecuta el snapshot, consulta la operación y verifica referencias y conteos
  de las cuatro particiones. El lock fue liberado; la limpieza restauró el
  mapping y los ajustes operacionales/sampler originales.
  `git diff --check`: pasó.
- **Supuestos nuevos:** los valores origen se normalizan con `strip` y
  `casefold`; el manager debe mapear explícitamente al menos un valor de cada
  clase. Los campos iniciales se copian al dataset snapshot con los nombres
  seleccionados en el esquema; la etiqueta objetivo de entrenamiento conserva
  el nombre canónico `fraud_label`. Se permite borrar toda la configuración
  de mapping (queda vacía y el
  muestreador no puede ejecutar hasta configurarla de nuevo), para restaurar
  un estado inicialmente no configurado.
- **Estado:** ajuste de H6 implementado; lint, arquitectura, pytest focalizado,
  lint/tipos frontend y E2E real pasaron. Pendiente de revisión/integración; no
  empezar otro hito.
- **Necesito del integrador:** integrar el ajuste backend y coordinar la
  integración frontend. Commits de este ajuste: backend `d1414ee`, frontend
  `8cf3d2e`; commits previos de H6: backend `bda9603` y frontend `a0313e9`
  (componente/API/E2E), `c8eb74c` (montaje de pestaña). No se requiere acción
  de B; el puerto contractual permanece intacto.

## FP2–FP3 — Chat compartido y modo asistente en el panel

- Commits frontend integrados: `69e6782` (panel compartido y chat) y `a50afba`
  (corrección de cleanup de efecto y E2E). La UI ofrece contexto de página,
  chat idempotente, insights y confirmación auditada de borradores.
- Verificación integradora: ESLint focalizado y `npx tsc --noEmit` pasaron.
  `make test-e2e-agent` reconstruyó el frontend integrado y Playwright pasó
  1/1 por nginx `http://localhost:80`, con chat idempotente y creación,
  verificación y confirmación de borrador contra el API real.
- El primer intento post-merge agotó el timeout del hook al recrear el API
  para obtener bootstrap. Se repitió con el API sano, config local montada
  desde integración y token temporal de bootstrap; el stack se devolvió a su
  configuración normal al terminar.

## Revisión integradora de regresiones (2026-10-20)

- La suite `make e2e-all-local` completa pasó 27/27 por nginx después de
  corregir la superposición del launcher sobre el CTA de despliegue y preparar
  los fixtures CSV de E05. E06 pasó con el timeout de cleanup actualizado a
  180 s. E01 también pasó en la suite completa.
- Lint Ruff/mypy 0/0, arquitectura 240/240, pytest focalizado de repositorios
  de configuración 22/22; `.lint-baseline.json` y los baselines conocidos no
  crecieron.

## FP4/FP5 — lanzamiento, conversación y progreso del optimizador

- Commits integrados: backend `c7717fb` (endpoint agregado de presupuesto) y
  frontend `43ce0f9` (panel del optimizador). El merge backend con H10 quedó en
  `3451384`.
- Verificación integrada: lint Ruff/mypy 0/0, arquitectura 240/240, pytest
  focalizado 35/35, ESLint focalizado, `npx tsc --noEmit` y `git diff --check`
  pasaron. Los baselines permanecen en cero.
- `E2E_TEST_FILES=e2e/agent-optimizer-real.spec.ts make e2e-all-local`
  reconstruyó API, worker y frontend y pasó 1/1 por nginx `http://localhost:80`
  con API same-origin `/api/v0`. Comprobó rechazo del rol manager, objetivo y
  presupuesto reales, lanzamiento por channel_manager, pausa, conversación y
  cancelación. Una ejecución anterior contra imagen frontend vieja expiró;
  reconstruir la imagen resolvió el problema.
- `make e2e-observability` pasó 1/1. La suite completa registró 19 pasadas,
  7 fallidas y 1 omitida: aserción de métricas de esquema; E11 respaldos,
  E01 login, E04 login, E03 entidades y E06 login con HTTP 500; E05 no encontró
  `/private/tmp/aria-e04-partitions/e04_actual_sanitized_900.csv`. Los E2E de
  FP4/FP5 y FP2/FP3 pasaron dentro de la suite.
- En la repetición focalizada, el API registró que `POST /api/v0/library/taxonomies`
  falla porque `tiktoken` intenta descargar `cl100k_base` y el contenedor no
  resuelve `openaipublic.blob.core.windows.net`. Las demás causas seguían sin
  confirmar en el corte del 2026-10-20; esa espera es histórica. El integrador
  declaró H11 cerrado; la sección histórica de
  `docs/handoff/HANDOFF-B.md` aún requiere alinear su estado.

## FP8 — UI y Playwright real por nginx (2026-10-21)

- Contraste con el router backend H12 y sus esquemas: se consumen las rutas
  existentes bajo `/api/v0/agent/releases` para validación retrospectiva,
  creación/listado SHADOW, submit, aprobación, avance y rollback. No se añadió
  endpoint ni se simularon respuestas. `channel_manager` valida/crea/envía;
  `manager` y `release_manager` leen y ejecutan aprobación/avance/rollback.
  La API rechaza aprobación de `channel_manager` (403), autoaprobación (409),
  envío sin 30 observaciones (409) y release simultáneo (409).
- La UI presenta el resultado de la validación (estado, snapshot/hash y pins),
  el estado/observaciones del release y acciones permitidas por rol. El avance
  solo se habilita con el mínimo de observaciones y rollback se oculta en estado
  terminal. El panel optimizador consulta los claims ya existentes por área;
  si otra sesión tiene el claim activo, muestra su `session_id` y `claimed_at`
  localizado. La prueba confirma que B devuelve 409 al crear otra sesión
  optimizadora mientras el área está reclamada; por eso el fixture crea una
  sesión borrador antes de iniciar la sesión que toma el claim.
- Archivos frontend tocados: `src/lib/api/agent.functions.ts`,
  `src/components/agent/AgentReleasePanel.tsx`,
  `src/components/agent/AgentOptimizerPanel.tsx`,
  `src/components/agent/AgentPanel.tsx`,
  `e2e/agent-assistant-real.spec.ts` y
  `e2e/agent-optimizer-real.spec.ts` en `../frontend_mockup`.
- Cobertura Playwright ejecutada: `npm run test:e2e:agent:optimizer:real`
  terminó **1 passed (13.5s)** por `http://localhost` (nginx), con API
  same-origin `/api`: claims reales por área, nombre/fecha de sesión activa
  desde la pestaña de otra sesión draft, lanzamiento, lease, historial,
  comparación/auditoría FP6/F7.4, pausa, conversación y cancelación. El E2E
  `npm run test:e2e:agent:real` sigue **pendiente**: primero ejecutó creación y
  edición pero falló porque el schema de confirmaciones no contiene
  `entity_id`; corregida la aserción para validar `action/status`, la repetición
  falló al generar el borrador de edición (HTTP 503 del servicio de generación)
  antes de confirmar la edición. No declaro ese recorrido cubierto.
- El E2E H12 default integrado pasó previamente: validación retrospectiva y
  creación SHADOW desde UI, 403 al intentar aprobar como channel_manager,
  409 al enviar sin evidencia, rollback de manager desde UI y candidato inactivo.
  Resultado completo conservado en el bloque H12 de este HANDOFF (sesión
  `818e7fbd-ce1b-49ab-a27c-97f0af13f547`, experimento
  `6c7e33fa-998a-4c3c-9dcf-e532fe00f7a5`).
- Intento de cobertura integrada completa:
  `H12_E2E_FULL=1 make e2e-agent-h12-resume-local`. API, worker y nginx se
  reconstruyeron, la retrospectiva/SHADOW se ejecutó por UI y el camino real
  generó la primera alerta con `POST /api/v0/alerts/test`; el review worker
  marcó esa alerta `FAILED` (adversarial review rechazó `customer_name='Mock
  Customer'` y `event_type='H12 rollout E2E'`). El comando terminó exit 2 antes
  de submit/aprobación/promoción. No se inyectaron observaciones ficticias.
  **Quedan pendientes** con evidencia backend: transición aprobada a
  `CANARY_5`, avance `CANARY_25`/`CANARY_50`/`FULL`, rollback posterior a FULL,
  y la promoción bloqueada/desbloqueada de extremo a extremo. La aprobación
  debe reintentarse con alertas que superen la política real de revisión.
  - Reejecución `make e2e-agent-h12-full-local` (2026-10-22): H8 y H11 pasaron
    por nginx; experimento `d5e2e491-f87f-4382-9d8e-83c49ac510ea`, snapshot
    `604667118b18f7d0a7122b0c22643b0d`, SHA-256
    `a29cf05f88f5849c6643186020bcf725f3ff8c35c925d90bf3524bd0bba1bf4b`.
    H12 validó retrospectiva y creó SHADOW, pero el primer review worker falló
    tras tres ciclos: el revisor encontró solo evidencia de alta velocidad y
    rechazó que `score=1.0` dominado por `amount` probara fraude. No hubo
    observaciones ni promoción. El prompt de clasificación se reforzó contra
    inferencias desde campos ausentes, velocidad y score, pero el fixture aún
    carece de evidencia positiva suficiente. El E2E no leyó el agregado tras el
    fallo; como el comparador registra activo/candidato antes de la revisión
    adversarial, el conteo de esta alerta queda sin verificar. No se relajaron guardrails; falta
    preparar un fixture con señal verificable o cubrir el bloqueo ante
    desacuerdo. El stack terminó abajo y el puerto 80 liberado.
  - Segundo intento (2026-10-22): enviar temporalmente `biocatch.isRat=true`
    tampoco completó el review worker. El adaptador ARIC local devuelve
    `aric_signals.is_rat=false`, prevalece sobre el payload, y el revisor marcó
    la inconsistencia tras tres ciclos. El E2E no consultó el agregado; pudo
    registrarse la comparación activo/candidato antes de la revisión. El worker terminó con
    `AdversarialFeedbackLimitExceededError`; el E2E venció la espera de 180 s.
    Los logs registran un reintento de llamada LLM y una respuesta posterior,
    así que no fue un fallo terminal de transporte. Se retiró el valor
    contradictorio; falta una fuente ARIC coherente o un fixture con decisiones
    concordantes. El stack quedó apagado.
- **Límites:** el E2E de claims cubre interferencia entre una sesión activa y
  una draft, no dos sesiones activas; el backend bloquea la segunda con 409.
  La edición asistida se ejecutó pero su aserción de auditoría aún requiere
  repetición. El flujo de insights vinculado a la sesión, varias iteraciones
  reales sin aprobación intermedia y pausa/cancelación con progreso del runner
  no están cubiertos por los resultados de esta corrida. No se afirma cobertura
  para ellos. La evidencia H12 disponible es local y sintética, sin despliegue
  ni rendimiento productivo.
- Verificaciones: ESLint focalizado y `npx tsc --noEmit` pasaron tras los
  cambios de UI/specs. `node --check scripts/e2e_agent_h12_local.mjs` y
  `git diff --check` pasaron antes de la última corrida; repetir
  `git diff --check` al cerrar. No se ejecutó la suite completa ni
  `make e2e-observability` para este cambio.
