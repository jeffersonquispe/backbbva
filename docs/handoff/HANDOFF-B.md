# Handoff Sesión B — H3 y H4

Fecha: 2026-10-19
Worktree: `../aria-wt-B`
Rama: `feat/agent-B`
Base tras rebase: `8864dba` (`DEMLGENAIF-141 docs(agent): record H1 and H2 integration results`)

## Qué quedó hecho

- Se completó la columna vertebral de H3: puertos y repositorios DynamoDB para sesiones, iteraciones, runs, llamadas a herramientas, ledger de presupuesto, verificaciones, paquetes, confirmaciones y prompts versionados con puntero activo.
- Se preservó el puerto `AssistantOptimizerSettingsPort` publicado por H2; no queda una definición duplicada. API y worker resuelven `DynamoAssistantOptimizerSettingsRepository` mediante su composición/factory.
- Se corrigió el mapeo persistido de prompts: el atributo/claves DynamoDB usan `prompt_name`; se mantiene `name` en el dominio y se convierte al leer. Las pruebas focalizadas del seed/mapeo pasan.
- El contrato `AgentSubagent` está conectado a `StubAgentSubagent`. El orquestador avanza un tick, vuelve a leer switches y topes en cada tick, registra lease/ledger/resultados y respeta cancelación y kill switch.
- Se añadieron `agent_app`, la cola aislada del agente, task de orquestación, task periódico de recuperación de leases vencidos y dispatcher. API, worker y beat se componen en factories.
- El compose local tiene worker y beat propios. Se añadió un E2E real por `http://localhost/api/v0` que valida kill switch, cancelación, matar el worker con `SIGKILL`, barrido/reintento y generación del paquete. El script usa usuario único por ejecución y restaura settings/token de bootstrap al finalizar.
- El E2E encontró que DynamoDB no acepta `NULL` como clave GSI `lease_expires_at`; el encoder ahora omite atributos `None`. También se detuvo el autoencolado infinito del modo assistant al pausar tras su iteración mínima.

## Archivos tocados

- `src/application/ports/agent_*_port.py`, `src/application/use_cases/agent/`
- `src/infrastructure/agents/`
- `src/infrastructure/persistence/database/dynamodb/repositories/agent_*.py`
- `src/infrastructure/persistence/database/dynamodb/{manager.py,schemas.py}`
- `src/infrastructure/entrypoint/api/{factories/agent_factory.py,routers/agent_router.py,schemas/agent.py,fastapi_app.py,initialization/tables.py}`
- `src/infrastructure/entrypoint/agent_worker/celery/{celery_app.py,tasks.py}`
- `src/infrastructure/queues/celery/{app.py,agent_dispatcher.py}`
- `src/infrastructure/workflows/celery/{factories.py,task_factories.py}`
- `src/infrastructure/core/config.py`, `config/local/gunicorn.conf.py`
- `deploy/local/docker/docker-compose.yml`, `Makefile`
- `scripts/e2e_agent_local.py`
- `tests/test_application/test_use_cases/test_orchestrate_agent_iteration.py`
- `tests/test_infrastructure/test_agents/`, `tests/test_infrastructure/test_entrypoint/test_agent_worker_celery_app.py`
- `docs/handoff/HANDOFF-B.md`

## Comandos y resultado real

- `make lint`: **pasó** — Ruff 0 errores (baseline 0); mypy 0 errores (baseline 0).
- `API_V0_STR=/api/v0 make test-architecture`: **pasó** — 223 passed; pytest mostró dos avisos de escritura de `.pytest_cache` en el worktree.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest tests/test_application/test_use_cases/test_orchestrate_agent_iteration.py tests/test_infrastructure/test_agents tests/test_infrastructure/test_entrypoint/test_agent_worker_celery_app.py`: **pasó** — 12 passed. Un aviso de escritura de `.pytest_cache`.
- `make e2e-agent-local`: stack reconstruido/levantado; E2E real por nginx **pasó**. El flujo reportó: `Agent E2E por nginx: kill switch, cancelación y recuperación pasaron.` Incluyó fallo intencional del worker con `SIGKILL`, run huérfano FAILED por lease vencido y run posterior SUCCEEDED con paquete.
- Hubo una ejecución focalizada inicial de pytest sin `API_V0_STR`; falló en colección porque la configuración requiere esa variable. Repetida con la variable, pasó 12/12.
- `make lint-baseline`: no ejecutado; los baselines permanecieron en cero.
- Commit local de H3: `f55be75` (`DEMLGENAIF-141 feat(agent): complete H3 worker orchestration`); sin push.

## E2E

**Pasó** en el stack local a través de nginx en `http://localhost` (puerto 80), con lock `/tmp/aria-e2e.lock` tomado durante la ejecución. El script restauró el token original y settings y el lock se liberó al terminar.

## Desvíos del modelo de datos propuesto

- Se añadieron las tablas H3 al manager y schemas Dynamo. El encoder omite atributos nulos para impedir que una clave GSI opcional llegue como `NULL`.
- No se añadieron registros manuales separados para catálogo de respaldos, cleaner E2E ni OKD porque su configuración actual deriva de las tablas registradas en el manager; no hay listas adicionales de tablas que actualizar en esos archivos.
- El atributo DynamoDB de prompts es `prompt_name`, como exige la clave propuesta; el modelo de dominio conserva `name`.

## Supuestos nuevos y dependencias

- El worker usa `DynamoAssistantOptimizerSettingsRepository` provisto por H2; no mantiene settings en memoria ni crea otro puerto.
- El modo assistant hace una iteración mínima y se pausa; el modo optimization continúa sujeto a topes y switches leídos por tick.
- No se inició H4.

## Qué necesito de A o del integrador

- **A:** H1+H2 integrados en `c1c9937`; H3 ya consume el repositorio de settings real.
- **Integrador:** H3 fue integrado sin conflictos en `37e5df4`. La revisión independiente pasó lint (Ruff 0, mypy 0), arquitectura (223) y pytest focalizado (12). `make e2e-agent-local` pasó por nginx con kill switch, cancelación y recuperación tras SIGKILL; `make e2e-observability` pasó (1). Suite completa posterior: 20 pasaron; E01 falló con HTTP 500 al aprobar despliegue, E04/E05 por CSV ausentes en `/private/tmp/aria-e04-partitions` y E10 por discrepancia entre el total esperado y el exportado. Estos fallos no recorren el flujo H3.
- **Estado:** H3 aceptado. B queda autorizado a iniciar H4 backend; H5 espera el cierre de H4. Frontend FP0/FP1 queda asignado a A junto con H6, con prioridad a H6 si compiten por capacidad.

---

## H4 backend — implementación lista para revisión

Worktree: `../aria-wt-B-H4`

Rama: `feat/agent-B-H4`

Base: `83326e2` (incluye integración H3 `37e5df4`)

### Qué quedó hecho

- Añadidos mensajes de chat idempotentes por `client_message_id`, insights con estados propuesto/confirmado/activo/rechazado/resultado terminal, enlaces mensaje→insight y resúmenes de sesión versionados.
- Se implementó `PersonalDataMasker` como puerto y adaptador por reglas para cédulas, NIT, celulares, cuentas, tarjetas, emails e IP. El texto se enmascara antes de persistirlo y antes de enviarlo al LLM; también se redactan propuestas y contenido de salida.
- El caso de uso verifica propietario, estado, switch `assistant_enabled` y límite de caracteres proveniente de settings. Contextualiza con resumen, insights activos y mensajes recientes; guarda el resumen extractivo acotado a 4000 caracteres.
- Se añadieron endpoints para enviar/listar mensajes, listar y confirmar/rechazar insights, consultar enlaces y resumen. Confirmar insight es una acción explícita de API; el chat no activa propuestas por un “sí”.
- Se añadió el prompt versionado `agent.chat.system`, su seed, tablas DynamoDB registradas en `manager.py`, catálogo explícito de backup y limpieza E2E.
- La API responde con error seguro `CHAT_UNAVAILABLE` si el proveedor/modelo LLM no está configurado. La suite de Playwright de chat usa navegador real y `/api/v0` por nginx; no simula respuestas API.
- La integración Azure reconoce deployments GPT-5 y usa `max_completion_tokens` sin forzar `temperature`; GPT-5.2 rechazaba `max_tokens` con `400 unsupported_parameter`. Se añadió esquema explícito para serializar enlaces de dominio.

### Archivos tocados

- `src/application/ports/{agent_chat_responder_port,agent_insight_port,agent_link_port,agent_message_port,agent_session_summary_port,personal_data_masker_port}.py`
- `src/application/ports/agent_session_port.py`
- `src/application/use_cases/agent/{chat_with_agent,manage_agent_insight,create_agent_session}.py`
- `src/infrastructure/agents/{factories,llm_chat_responder,prompt_seed,rule_based_personal_data_masker}.py`
- `src/infrastructure/llm/langchain/azure_llm_unit_of_work.py`
- `src/infrastructure/agents/prompts/agent.chat.system.txt`
- `src/infrastructure/entrypoint/api/{factories/agent_factory.py,routers/agent_router.py,schemas/agent.py}`
- `src/infrastructure/persistence/database/dynamodb/{schemas.py,manager.py,repositories/agent_chat_repositories.py,repositories/agent_session_repository.py,repositories/e2e_state_cleaner.py}`
- `scripts/db_backup.py`, `scripts/e2e_agent_chat_local.mjs`, `Makefile`
- `tests/test_application/test_use_cases/test_chat_with_agent.py`
- `tests/test_infrastructure/test_agents/{test_llm_chat_responder.py,test_personal_data_masker.py}`
- `tests/test_infrastructure/test_llm/test_azure_llm_unit_of_work.py`
- `tests/test_infrastructure/test_entrypoint/test_agent_schemas.py`
- `docs/handoff/HANDOFF-B.md`

### Comandos y resultado real

- `RUFF_CACHE_DIR=/tmp/aria-ruff-cache-B-H4 make lint`: **pasó** — Ruff 0 errores (baseline 0), mypy 0 errores (baseline 0). La ejecución inicial sin `RUFF_CACHE_DIR` fue bloqueada al crear `.ruff_cache` por permisos del worktree; los resultados no se aceptaron hasta repetir y pasar.
- `API_V0_STR=/api/v0 make test-architecture`: **pasó** — 225 passed. pytest dio un aviso de permisos al crear `.pytest_cache` en el worktree.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest tests/test_infrastructure/test_llm/test_azure_llm_unit_of_work.py tests/test_infrastructure/test_agents/test_llm_chat_responder.py tests/test_application/test_use_cases/test_chat_with_agent.py tests/test_infrastructure/test_agents/test_personal_data_masker.py tests/test_infrastructure/test_agents/test_prompt_dynamodb_mapping.py tests/test_infrastructure/test_entrypoint/test_agent_schemas.py`: **pasó** — 13 passed; un aviso de permisos al crear `.pytest_cache`.
- `make e2e-agent-chat-local`: **pasó** — reconstruyó el API, usó Playwright real contra `http://localhost` por nginx y completó máscara, inyección, reintento, insight, enlace y resumen. Salida: `Agent chat E2E Playwright por nginx: máscara, inyección, reintento, insight, enlace y resumen pasaron.` El target obtuvo `/tmp/aria-e2e.lock` y su `trap` lo liberó.
- Durante el diagnóstico, el primer E2E con configuración presente identificó el parámetro Azure `max_tokens` como incompatible (`400 unsupported_parameter`); el ajuste GPT-5 se probó con una llamada inocua y luego con la suite E2E completa.
- `node --check scripts/e2e_agent_chat_local.mjs` y `git diff --check`: **pasaron**.
- `node --check scripts/e2e_agent_chat_local.mjs`: **pasó**.
- `git diff --check`: **pasó**.
- No se ejecutó `make lint-baseline`; los baselines siguen en cero.

### E2E

**Pasó.** E2E real por nginx en `http://localhost` (puerto 80), sin mocks de API. Verificó reintento con el mismo `client_message_id` sin duplicar mensajes, enmascarado de señuelos de datos colombianos en respuestas/logs, resistencia a inyección, insight pendiente hasta confirmación API, relación mensaje→insight y resumen versionado. El lock se liberó.

### Desvíos del modelo de datos propuesto

- `message_seq` es contador atómico en `agent_sessions` (incremento `ADD` más `rev`) y no contador separado; evita que actualizaciones stale reinicien el orden.
- La clave primaria de idempotencia de mensaje es `(session_id, client_message_id)`; el orden cronológico se consulta por índice GSI de secuencia.
- Los resúmenes son append-only, extractivos y acotados a 4000 caracteres; no hay carryover automático entre sesiones. Insights requieren confirmación explícita en la sesión correspondiente.
- TTL persiste como epoch numérico. DynamoDB Local rechaza `UpdateTimeToLive` con `ValidationException` en estas tablas, por lo que el borrado automático por TTL no pudo validarse localmente.
- Las cuatro tablas nuevas se registran en `manager.py`, backup y cleaner; no se modificó un manifiesto OKD independiente porque el despliegue usa el registro compartido de tablas. Revisar con integrador que ese registro sea la fuente efectiva para OKD.

### Supuestos nuevos y dependencias

- El chat depende de la configuración LLM local real; no se introdujo stub para forzar el E2E.
- La confirmación de insight es una llamada API auditada separada y nunca se infiere de texto conversacional.
- Frontend FP0/FP1 sigue a cargo de A. No se inició H5.

### Qué necesito de A o del integrador

- **Integrador:** revisar H4 y el desvío de catálogo OKD. El E2E real ya pasó; H5 queda pendiente de aceptación/revisión del integrador.

---

## H5 — primer tipo: modus operandi con playbook — listo para revisión

Worktree: `../aria-wt-B-H5`

Rama: `feat/agent-B-H5`

Base: `e2d844f` (integración H4)

### Qué quedó hecho

- Se añadió el subagente generador de modus operandi, usando el contrato de subagente existente y el flujo H4 para leer mensajes ya enmascarados. Se registró el prompt inmutable `agent.modus_operandi.generate` en el seed.
- Se implementó generación de paquetes inmutables para `create` y `update`, con procedencia por campo, diff, `base_version` y verificaciones deterministas de esquema, taxonomía, duplicados, coherencia de fallbacks del playbook y fuga de PII. Las verificaciones se persisten en el paquete.
- La confirmación es una acción explícita de API, separada del chat. Verifica ownership, estado, resultados, duplicados y vigencia de `base_version`; registra confirmación append-only y eventos auditados antes/después de aplicar por los casos de uso existentes de creación/actualización y su embedding. La actualización DynamoDB usa condición sobre `updated_at` para evitar aplicar sobre una revisión concurrente.
- La API permite generar/leer paquetes, confirmar explícitamente y consultar confirmaciones. Se añadió E2E Playwright real que cubre alta y edición completas detrás de nginx.

### Archivos tocados

- `src/application/ports/agent_confirmation_port.py`, `src/application/ports/agent_modus_operandi_draft_applier_port.py`, `src/application/ports/modus_operandi_library_port.py`
- `src/application/use_cases/agent/draft_modus_operandi.py`
- `src/application/use_cases/modus_operandi_library/{create_modus_operandi_library_entry.py,update_modus_operandi_library_entry.py,playbook_validation.py}`
- `src/infrastructure/agents/{factories.py,modus_operandi_draft_applier.py,modus_operandi_generator_subagent.py,prompt_seed.py}`
- `src/infrastructure/agents/prompts/agent.modus_operandi.generate.txt`
- `src/infrastructure/entrypoint/api/{fastapi_app.py,schemas/agent.py,factories/agent_modus_operandi_draft_factory.py,routers/agent_modus_operandi_draft_router.py}`
- `src/infrastructure/persistence/database/dynamodb/repositories/modus_operandi_library_repository.py`
- `scripts/e2e_agent_modus_operandi_local.mjs`, `Makefile`
- `tests/test_application/test_use_cases/{test_draft_modus_operandi.py,test_modus_operandi_library.py}`
- `docs/handoff/HANDOFF-B.md`

### Comandos y resultado real

- `RUFF_CACHE_DIR=/tmp/aria-ruff-cache-B-H5 make lint`: **pasó** — Ruff 0 errores (baseline 0), mypy 0 errores (baseline 0).
- `API_V0_STR=/api/v0 make test-architecture`: **pasó** — 227 passed; dos avisos de permisos de escritura de `.pytest_cache` en el worktree.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest tests/test_application/test_use_cases/test_draft_modus_operandi.py tests/test_application/test_use_cases/test_modus_operandi_library.py tests/test_infrastructure/test_entrypoint/test_agent_schemas.py`: **pasó** — 17 passed; un aviso de permisos de `.pytest_cache`.
- `node --check scripts/e2e_agent_modus_operandi_local.mjs`: **pasó**.
- `make e2e-agent-modus-operandi-local`: **pasó** con Playwright/navegador real, API por nginx `http://localhost` y lock `/tmp/aria-e2e.lock`; salida: `Agent H5 E2E por nginx: modus operandi create/update, verificaciones, diff, base_version y auditoría pasaron.` El target liberó el lock al terminar.
- En la primera ejecución el flujo creó y confirmó correctamente, pero el probe de auditoría no paginaba el scan DynamoDB. Tras paginarlo, una segunda ejecución detectó diferencias de representación ISO de la misma fecha en el `base_version`; el E2E ahora compara instantes normalizados. La ejecución final pasó de extremo a extremo.
- La primera colección de `make test-architecture` no recibió `API_V0_STR` y falló por configuración requerida; repetido con `API_V0_STR=/api/v0`, pasó 227/227.
- No se ejecutó `make lint-baseline`; los baselines no crecieron. E2E real ejecutado con el lock obligatorio; no se ejecutó la suite completa `make e2e-all-local`.

### E2E

**Pasó** el E2E específico por nginx en `http://localhost` (puerto 80), con Docker y proveedor LLM configurado en el stack local, sin mocks de API. El navegador creó y confirmó un modus operandi con playbook, leyó la entidad aplicada, generó y confirmó una edición sobre su versión base, y comprobó verificaciones, diff, procedencia, confirmaciones persistidas y auditoría. El lock se liberó.

### Desvíos del modelo de datos propuesto

- Se reutilizan `agent_packages`, `agent_verifications` y `agent_confirmations` de H3/H4; no se crean tablas nuevas ni cambian claves/índices, por lo que no se requieren altas adicionales en manager, backup, cleaner u OKD.
- `base_version` es el `updated_at` ISO de la entidad. Su escritura condicional en DynamoDB convierte la comprobación previa en protección ante una actualización concurrente; la comparación en el cliente del E2E normaliza representación de zona horaria.
- La confirmación añade al registro existente rol, versión base, estados de verificadores y mensaje fuente para mantener la evidencia append-only. El paquete conserva nombre, versión y hash del prompt.
- Para compatibilidad con sesiones H4 existentes cuyo pin de prompts antecede al prompt generador, se registra y se usa la referencia activa del generador cuando la sesión no tenga ese prompt específico fijado.

### Supuestos nuevos y dependencias

- Esta entrega cubre únicamente `modus_operandi` con playbook. Los demás tipos de entidad quedan separados y no se iniciaron.
- La aplicación confirmada reutiliza los casos de uso existentes de biblioteca para persistencia y embedding; no existe una ruta de escritura paralela.
- La protección de PII reutiliza el masker H4 antes de derivar contenido. El chat, aunque responda “sí”, no confirma paquetes.
- La suite E2E específica es una nueva cobertura de browser; no sustituye la suite completa local, que no se ejecutó en este hito.

### Qué necesito de A o del integrador

- **A:** ninguna dependencia nueva para este primer tipo; se consumen los contratos H4 integrados.
- **Integrador:** revisar el primer entregable H5, incluidos el uso de `updated_at` como `base_version`, los eventos de auditoría y la verificación E2E. No iniciar otros tipos de entidad hasta recibir revisión.

### Corrección posterior: fallo `409 DRAFT_POLICY` observado en tronco

- **Causa en el código:** el subagente H5 estaba conectado a `LLMChatResponder` de H4. Ese adaptador agrega instrucciones de chat que exigen una envoltura `{"text": ..., "proposals": [...]}` y una respuesta conversacional agregada, mientras que el generador H5 necesita el objeto de entidad JSON crudo. Cuando la salida no cumplía el contrato H5, el subagente devolvía `GENERATION_INVALID`; el caso de uso lo convertía indebidamente en `AgentDraftPolicyError` y la API lo exponía como `409 DRAFT_POLICY`. El cuerpo crudo del proveedor no se persiste ni se registra por las reglas de privacidad, pero la ruta de clasificación está cubierta por el código y el contrato contradictorio quedó eliminado.
- **Corrección:** se añadió el puerto `AgentStructuredGenerator` y su adaptador LLM propio, con el prompt H5 como único mensaje de sistema y redacción de spans compartida con el responder H4. Las salidas inválidas ahora se clasifican como indisponibilidad de generación (`503 DRAFT_GENERATION_UNAVAILABLE`), no como política. El prompt especifica que un update conserva literalmente los campos que el usuario no edita, incluido el playbook.
- **Archivos adicionales/modificados:** `src/application/ports/agent_structured_generator_port.py`; `src/infrastructure/agents/{content_redacting_monitoring.py,llm_structured_agent_generator.py,modus_operandi_generator_subagent.py,llm_chat_responder.py,factories.py}`; `src/application/use_cases/agent/draft_modus_operandi.py`; `src/infrastructure/entrypoint/api/routers/agent_modus_operandi_draft_router.py`; `src/infrastructure/agents/prompts/agent.modus_operandi.generate.txt`; `scripts/e2e_agent_modus_operandi_local.mjs`; `tests/test_infrastructure/test_agents/test_llm_structured_agent_generator.py`; `docs/handoff/HANDOFF-B.md`.
- **Evidencia de comandos:** `RUFF_CACHE_DIR=/tmp/aria-ruff-cache-B-H5 make lint`: pasó (Ruff 0, mypy 0, baseline 0). `API_V0_STR=/api/v0 make test-architecture`: pasó (227). `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest tests/test_application/test_use_cases/test_draft_modus_operandi.py tests/test_application/test_use_cases/test_modus_operandi_library.py tests/test_infrastructure/test_entrypoint/test_agent_schemas.py tests/test_infrastructure/test_agents/test_llm_chat_responder.py tests/test_infrastructure/test_agents/test_llm_structured_agent_generator.py`: pasó (19). `node --check scripts/e2e_agent_modus_operandi_local.mjs` y `git diff --check`: pasaron.
- **E2E:** `make e2e-agent-modus-operandi-local` volvió a pasar por Playwright real vía nginx `http://localhost`: create y update, verificaciones, diff, `base_version`, confirmaciones y auditoría. Salida: `Agent H5 E2E por nginx: modus operandi create/update, verificaciones, diff, base_version y auditoría pasaron.` El target esperó el lock compartido, lo tomó y su `trap` lo liberó; la suite compartida volvió a crear el lock al terminar, y se dejó intacto.
- Durante la primera reproducción con el adaptador separado, create pasó; el E2E alcanzó update y detectó que el mensaje de prueba no precisaba conservar la estrategia y la resolución primaria. Se aclaró la semántica de patch en el prompt y se hizo explícito el playbook a preservar en el mensaje E2E; la ejecución final pasó los dos caminos.
- **Estado:** corregido y listo para revisión del integrador. El resultado anterior `113fd03` necesita una actualización con esta corrección antes de otro merge; no se inició otro tipo de entidad.

---

## H8 — objetivos versionados y evaluación global — listo para revisión

Worktree: `../aria-wt-B-H8`

Rama: `feat/agent-B-H8`

Base: `3fe3198`

### Qué quedó hecho

- Se añadió el dominio de objetivos versionados (`DRAFT`, `ACTIVE`, `RETIRED`), endpoints para listar/crear versiones y activar con control de versión esperada, y persistencia DynamoDB con actualización condicional del puntero activo.
- Se añadió evaluación global para una sola ejecución por snapshot: compara candidato `READY` contra baseline activo exclusivamente en la partición final reservada; excluye filas con etiqueta pendiente y calcula precision, recall, soporte, cobertura e intervalo bootstrap pareado determinista. El resultado agregado queda asociado al registro de verificaciones del snapshot.
- Se añadió el puerto del evaluador de pipeline, el caso de uso, dispatcher Celery y la tarea `optimizer.evaluate_global_pipeline`, con composición en factories de tareas.
- La creación de snapshots de muestra madura conserva las features seguras necesarias para inferencia, omite etiquetas y campos de fecha de marcación en el conjunto de entrenamiento; el split `all` no contiene la partición final. El entrenamiento H6 usa train/validation/calibration y excluye `final`.
- Se amplió `scripts/e2e_agent_local.py` para ejercitar API real de listar, crear y activar un objetivo. En la última ejecución también pasaron los escenarios existentes de kill switch, cancelación y recuperación del worker.
- Se añadió `scripts/e2e_global_pipeline_local.py` y el target `make e2e-agent-global-pipeline-local`: siembra datos sintéticos locales, genera el snapshot por API, entrena baseline y candidato mediante workers reales y comprueba la evaluación global por API detrás de nginx.
- El evaluador de Celery ahora usa `MCPModelScoringClient.score_row` para puntuar ambos modelos. Así el worker del agente no carga artefactos con `joblib` ni requiere dependencias de entrenamiento; MCP conserva el runtime de ML.

### Archivos tocados

- `src/domain/agents/objective.py`
- `src/application/ports/{agent_objective_port.py,global_pipeline_evaluation_port.py,model_pipeline_evaluator_port.py,agent_verification_port.py,model_scoring_port.py}`
- `src/application/use_cases/agent/{manage_agent_objective.py,evaluate_global_pipeline.py}`
- `src/application/use_cases/datasets/create_mature_sample_snapshot.py`
- `src/infrastructure/entrypoint/api/{fastapi_app.py,schemas/agent_objectives.py,factories/agent_objective_factory.py,routers/agent_objectives_router.py}`
- `src/infrastructure/entrypoint/agent_worker/celery/tasks.py`
- `src/infrastructure/persistence/database/dynamodb/{schemas.py,manager.py,repositories/agent_objective_repository.py,repositories/agent_repositories.py,repositories/e2e_state_cleaner.py}`
- `src/infrastructure/queues/celery/global_pipeline_evaluation_dispatcher.py`
- `src/infrastructure/workflows/celery/{model_pipeline_evaluator.py,model_evaluation.py,task_factories.py}`
- `tests/test_application/test_use_cases/{test_agent_objective.py,test_evaluate_global_pipeline.py,test_create_mature_sample_snapshot.py}`
- `tests/test_infrastructure/test_workflows/{test_model_training.py,test_model_pipeline_evaluator.py}`
- `scripts/{e2e_agent_local.py,e2e_global_pipeline_local.py}`
- `Makefile`
- `docs/handoff/HANDOFF-B.md`

### Comandos y resultado real

- `RUFF_CACHE_DIR=/tmp/aria-ruff-cache-B-H8 make lint`: **pasó** — Ruff 0 errores (baseline 0), mypy 0 errores (baseline 0).
- `API_V0_STR=/api/v0 make test-architecture`: **pasó** — 236 pruebas.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest tests/test_application/test_use_cases/test_agent_objective.py tests/test_application/test_use_cases/test_evaluate_global_pipeline.py tests/test_application/test_use_cases/test_create_mature_sample_snapshot.py tests/test_infrastructure/test_workflows/test_model_training.py tests/test_infrastructure/test_workflows/test_model_pipeline_evaluator.py`: **pasó** — 11 pruebas; un aviso de `.pytest_cache` por permisos de escritura del worktree.
- `RUFF_CACHE_DIR=/tmp/aria-ruff-cache-B-H8 ruff check scripts/e2e_global_pipeline_local.py`, `PYTHONPYCACHEPREFIX=/tmp/aria-pycache-B-H8 python -m py_compile scripts/e2e_global_pipeline_local.py` y `git diff --check`: **pasaron**.
- `make e2e-agent-global-pipeline-local`: **pasó**; reconstruyó API, worker de entrenamiento y worker del agente y ejecutó el escenario con el lock compartido. Salida: `Muestra H8: eligible=3000, estimated=2991` y `H8 E2E por nginx: baseline READY vs candidato READY evaluados sobre partición final (271 filas etiquetadas).` API por nginx en `http://localhost:80`, sin mocks; creación del snapshot, entrenamiento de ambos modelos y evaluación corrieron en el stack real. El lock se liberó.
- Durante las iteraciones del E2E se detectó que el evaluador original importaba `joblib` en el worker del agente, dependía de una fecha de fixture UTC un día más joven que el calendario Bogotá, y que los snapshots finales se reservan una sola vez. Se corrigió el evaluador para usar MCP, se alineó el fixture a la zona de operación, se garantiza soporte suficiente y el harness limpia sus alertas sintéticas y genera un snapshot nuevo en cada ejecución.
- En las iteraciones previas del harness se corrigieron la discrepancia de fecha UTC/Bogotá en la elegibilidad, la configuración de tamaño para garantizar soporte final y la unicidad del snapshot E2E, porque la partición final se reserva una sola vez. El harness también elimina por marca sus alertas sintéticas locales antes y después del escenario.
- No se ejecutaron `make e2e-all-local` ni `make e2e-observability`. No se ejecutó `make lint-baseline`; baselines no crecieron.

### E2E y bloqueo pendiente

**Pasó** el E2E real del comportamiento principal de H8: creó un snapshot maduro con partición `final`, entrenó dos modelos `READY`, activó uno como baseline y evaluó el candidato sobre 271 filas etiquetadas de la partición reservada. El resultado llegó por el endpoint de estado y la tarea Celery real. El escenario usó datos generados en DynamoDB Local solo como fixture; las operaciones funcionales se hicieron por la API detrás de nginx en `http://localhost:80`, sin mocks de API. Se tomó y liberó `/tmp/aria-e2e.lock`.

### Desvíos del modelo de datos propuesto

- El puntero activo se guarda en la tabla nueva `agent_objective_active`, separada de `agent_objectives`; el layout transaccional propuesto inicialmente no funcionó en DynamoDB Local. La activación usa escrituras condicionales y compensación a `DRAFT` al detectar conflicto; el retiro de la versión anterior ocurre después de mover el puntero.
- Se reutiliza `agent_verifications` como almacenamiento agregado de una evaluación global por snapshot; no se agregó tabla de evaluación independiente.
- Los snapshots maduros incluyen features seguras del caso, sin etiqueta objetivo ni última fecha de marcación en el conjunto usado para entrenar. La partición `final` se conserva por separado para evaluación.
- El scorer del evaluador ejecuta `score_row` por MCP, en vez de abrir los objetos del modelo desde el worker del agente. Esto mantiene las dependencias ML en el servicio MCP, conforme a la división de runtime existente.
- Las dos tablas nuevas (`agent_objectives`, `agent_objective_active`) ya están registradas en `manager.py` y el cleaner. El integrador confirmó que el backup descubre tablas desde `schemas.py` y OKD las aprovisiona al iniciar la API; no se necesitaron cambios adicionales en esos componentes.

### Supuestos nuevos y dependencias

- El tipo de métrica global queda fijado a precision/recall/soporte/cobertura e intervalo bootstrap pareado; una comparación sin filas finales etiquetadas no se considera válida.
- Se asume que los artefactos de candidato y baseline quedan publicados con estado `READY` y son compatibles con el snapshot final antes de despachar la evaluación. El E2E crea ambos por el flujo real de entrenamiento.
- La evaluación se reserva por snapshot para impedir repeticiones sobre la partición final; resultados y métricas guardan agregados, sin valores por fila ni datos personales.
- El harness varía la duración del periodo de muestreo en cada ejecución para obtener un snapshot nuevo; una evaluación ya reservada no se puede repetir sobre el mismo snapshot.

### Qué necesito de A o del integrador

- **Integrador:** revisar H8 y sus evidencias; el respaldo/OKD no requiere cambios según la confirmación recibida. No hay dependencia pendiente de A.
- No se inició otro hito después de H8. Queda listo para revisión; esperar aceptación antes de continuar.

---

## H9 — orquestador del optimizador (backend) — listo para revisión

Worktree: `../aria-wt-B-H9`

Rama: `feat/agent-B-H9`

Base: `40c8c41` (H8 integrado)

### Qué quedó hecho

- El worker mantiene reclamos persistidos por área y lease; el API consulta solo reclamos no vencidos de sesiones activas para avisar interferencia.
- El loop de optimización crea hipótesis persistidas desde insights activos confirmados o, si no hay, desde el alcance. Prioriza con una regla determinista por tipo de insight y desempata por fecha e ID.
- Cada hipótesis guarda la verificación que la evaluó y el resultado agregado. Cuando hay evidencia suficiente, el insight de origen pasa a aplicado o refutado y queda un enlace a la verificación; sin métricas suficientes se conserva como no concluyente.
- El loop añade su estado al resumen versionado de sesión. Detiene la sesión ante un fallo crítico, estancamiento según el recall sujeto al piso de precisión, o falta de hipótesis activas. La política y el kill switch continúan leyéndose desde los settings actuales en cada tick.
- `channel_manager` puede autorizar renovaciones únicamente con la sesión pausada. El límite de renovaciones se consulta desde settings y cada ampliación añade entradas `RENEW` append-only al ledger. El response expone el contador persistido.
- El API expone hipótesis e iteraciones con campos seguros, además de reclamos por entidad y renovación de presupuesto.
- Se amplió el E2E API existente para comprobar el ciclo de kill switch, cancelación y recuperación, y se añadió un E2E Playwright H9 por nginx para hipótesis/evidencia, reclamo, pausa y renovación auditada.

### Diff y archivos tocados

- `src/application/ports/agent_{entity_claim,hypothesis}_port.py`, `src/application/ports/agent_session_port.py` y `src/application/use_cases/agent/{manage_agent_entity_claims,renew_agent_budget,orchestrate_agent_iteration}.py`.
- `src/infrastructure/persistence/database/dynamodb/{schemas.py,manager.py,repositories/agent_repositories.py,repositories/agent_session_repository.py,repositories/e2e_state_cleaner.py}`.
- `src/infrastructure/agents/factories.py`, `src/infrastructure/workflows/celery/{factories.py,task_factories.py}` y `src/infrastructure/entrypoint/agent_worker/celery/tasks.py`.
- `src/infrastructure/entrypoint/api/{factories/agent_factory.py,routers/agent_router.py,schemas/agent.py}`.
- `tests/test_application/test_use_cases/{test_agent_h9_coordination.py,test_orchestrate_agent_iteration.py}`, `tests/test_infrastructure/test_persistence/test_agent_session_repository.py`.
- `scripts/e2e_agent_local.py`, `scripts/e2e_agent_h9_local.mjs` y `Makefile` (`e2e-agent-h9-local`).
- `docs/handoff/HANDOFF-B.md`.

### Comandos y resultado real

- `RUFF_CACHE_DIR=/tmp/aria-ruff-cache-B-H9 make lint`: **pasó** — Ruff 0, mypy 0, ambos baselines 0.
- `API_V0_STR=/api/v0 make test-architecture`: **pasó** — 240/240.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest -q tests/test_application/test_use_cases/test_orchestrate_agent_iteration.py tests/test_application/test_use_cases/test_agent_h9_coordination.py tests/test_infrastructure/test_persistence/test_agent_session_repository.py tests/test_infrastructure/test_entrypoint/test_agent_schemas.py tests/test_infrastructure/test_entrypoint/test_agent_worker_celery_app.py`: **pasó** — 14 pruebas. Pytest emitió un aviso porque el sandbox no permite crear `.pytest_cache` dentro del worktree.
- `node --check scripts/e2e_agent_h9_local.mjs` y `git diff --check`: **pasaron**.
- `make e2e-agent-local`, con `/tmp/aria-e2e.lock`: **pasó** — `Agent E2E por nginx: kill switch, cancelación, recuperación, reclamo de alcance y renovación de presupuesto pasaron.` El escenario también consultó por API la hipótesis con su `evidence_id` y su salida `NONCONCLUSIVE`.
- `make e2e-agent-h9-local`: **pasó** — Playwright real en `http://localhost`, API por el proxy same-origin `/api/v0`, sin mocks. Salida: `H9 Playwright por nginx: hipótesis y evidencia, reclamo de alcance, pausa e incremento auditado de presupuesto pasaron.` El target tomó `/tmp/aria-e2e.lock` y lo liberó.
- La primera corrida con Docker fue bloqueada por permiso de Buildx para escribir su actividad bajo `~/.docker`. La siguiente detectó un `502` transitorio al recrear el worker porque Compose también recrea API; se añadió espera de salud en el harness. La corrida final reconstruida pasó.

### Estado E2E

**Pasó** por los dos caminos: escenario API de ciclo/recuperación y Playwright del comportamiento H9. Ambos usaron stack local real, nginx en puerto 80 y DynamoDB Local; los requests funcionales entraron por `/api/v0`.

### Desvíos del modelo de datos propuesto

- Se añadieron `agent_hypotheses` con clave `session_id` + `hypothesis_id` para historial y concurrencia por sesión.
- Se añadieron reclamos en `agent_entity_claims` con clave `entity_key` + `session_id` y GSI `SessionIdx` para heartbeat/liberación por sesión.
- No se modificó backup ni inicialización OKD: el backup enumera esquemas de `schemas.py` y la API aprovisiona tablas de esos esquemas al arrancar con DynamoDB configurado. El cleaner agrupa explícitamente ambas tablas como H9.
- La evidencia se guarda como referencia a `agent_verifications`; las métricas siguen siendo agregadas y no hay datos por caso. La renovación usa el ledger existente y el campo nuevo `budget_renewals` en `agent_sessions`.

### Supuestos nuevos y dependencias

- Solo los insights en estado activo alimentan hipótesis; los propuestos sin confirmación no se usan. Prioridad fija por tipo: directiva, hipótesis, restricción, preferencia, observación, decisión y pregunta.
- Cuando no existen insights activos, se crea una hipótesis inicial determinista según el primer ámbito del alcance ordenado. Al quedarse sin hipótesis activas, la sesión se detiene por `no_signal`.
- El estancamiento cuenta iteraciones sin mejora con métricas numéricas, usando recall como objetivo y precisión como piso; resultados por debajo del piso no se tratan como mejoras.
- La interfaz FP4/FP5 no se tocó porque esta sesión trabaja solo backend. No se ejecutaron `make e2e-all-local` ni `make e2e-observability`; no se ejecutó `make lint-baseline` porque los baselines no crecieron.

### Qué necesito de A o del integrador

- **A:** integrar FP4/FP5 de frontend contra los endpoints de progreso, hipótesis, reclamos e incremento de presupuesto, manteniendo el acceso same-origin.
- **Integrador:** revisar H9 backend y sus dos E2E. No se inició H10 ni se creó commit; esperar revisión antes de avanzar.

---

## H10 — enrutamiento y verificación de especialistas (backend) — listo para revisión

Worktree: `../aria-wt-B-H10`

Rama: `feat/agent-B-H10`

Base: `c65cea0` (H9 integrado)

### Qué quedó hecho

- El orquestador selecciona un especialista por hipótesis/área: configuración, Biblioteca, Vector Store o XGBoost. Si el experimento anterior no quedó verificado, dirige el siguiente a Biblioteca para inspección; el selector no impone un ciclo fijo.
- El resultado de cada iteración registra el nombre del especialista, el estado de verificación y si el experimento quedó verificado. La API expone esos campos agregados en el listado de iteraciones.
- Una hipótesis solo puede quedar VALIDATED/REFUTED con estado `PASSED`, sin código de error y con métricas requeridas. Los resultados `PENDING_VERIFICATION` se guardan como `NONCONCLUSIVE`.
- El worker compone cuatro generadores estructurados con prompts versionados y fijados por sesión. Validan el contrato de cada candidato: cambios de configuración sin operación/infra, borradores de entidades con resumen de evidencia, manifiesto y consultas autorizadas de Vector Store, y parámetros XGBoost dentro de rangos aprobados.
- Se enmascaran hipótesis, alcance y texto generado, y se descartan claves con customer_id, case_id o row_id. Las propuestas válidas se persisten como paquetes PENDING_VERIFICATION; las métricas de propuestas no verificadas no afectan la decisión ni validan hipótesis.
- Las sesiones de optimización fijan la versión activa del objetivo global H8; el worker recupera esa versión y usa su piso de precisión. Sin objetivo activo no crea la sesión. La referencia queda en sesión y en la iteración.
- El E2E Playwright real comprueba por nginx que una sesión de modelo selecciona XGBoost y, ante la ausencia de proveedor, el worker falla de forma segura, deja la hipótesis no concluyente y libera el reclamo.

### Diff y archivos tocados

- `src/application/use_cases/agent/orchestrate_agent_iteration.py`
- `src/application/ports/{agent_session_port.py,agent_subagent_port.py}`, `src/application/use_cases/agent/{create_agent_session.py,manage_agent_objective.py,orchestrate_agent_iteration.py}`, `src/domain/agents/objective.py`
- `src/infrastructure/agents/{optimizer_specialist_subagent.py,factories.py,prompt_seed.py,llm_structured_agent_generator.py}` y cuatro prompts de especialista
- `src/infrastructure/agents/stub_subagent.py`
- `src/infrastructure/workflows/celery/factories.py`
- `src/infrastructure/entrypoint/api/{factories/agent_factory.py,routers/agent_router.py,schemas/agent.py}`
- `src/infrastructure/persistence/database/dynamodb/repositories/agent_session_repository.py`
- `tests/test_application/test_use_cases/{test_create_agent_session.py,test_orchestrate_agent_iteration.py}`
- `tests/test_infrastructure/test_agents/test_optimizer_specialist_subagent.py`, `tests/test_infrastructure/test_persistence/test_agent_session_repository.py`
- `scripts/e2e_agent_h9_local.mjs`, `Makefile` (target `e2e-agent-h10-local`)
- `docs/handoff/HANDOFF-B.md`

### Comandos y resultado real

- `RUFF_CACHE_DIR=/tmp/aria-ruff-cache-B-H10 make lint`: **pasó** — Ruff 0 errores (baseline 0), mypy 0 errores (baseline 0).
- `PYTEST_ADDOPTS='-p no:cacheprovider' API_V0_STR=/api/v0 make test-architecture`: **pasó** — 240/240, sin advertencia de caché.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest -p no:cacheprovider tests/test_application/test_use_cases/test_create_agent_session.py tests/test_application/test_use_cases/test_orchestrate_agent_iteration.py tests/test_infrastructure/test_agents/test_optimizer_specialist_subagent.py tests/test_infrastructure/test_persistence/test_agent_session_repository.py tests/test_infrastructure/test_agents/test_stub_subagent.py tests/test_infrastructure/test_entrypoint/test_agent_schemas.py tests/test_infrastructure/test_agents/test_prompt_dynamodb_mapping.py`: **pasó** — 28/28.
- `git diff --check`: **pasó**.
- `make e2e-agent-h10-local`: **pasó** el escenario fail-closed, reconstruyendo el stack y usando nginx. El primer intento con generadores reales acabó en HTTP 409 BUDGET_RENEWAL_POLICY: al no haber modelo LLM configurado, la sesión se detuvo por fallo crítico y el harness intentó renovar un presupuesto terminal. Se ajustó el escenario H10 y la repetición final pasó: objetivo fijado, selección XGBoost, fallo seguro del proveedor, hipótesis no concluyente y liberación del reclamo. El target tomó y liberó `/tmp/aria-e2e.lock`.

### E2E

**Pasó el escenario fail-closed** por Playwright real a `http://localhost:80`, con tráfico API same-origin `/api/v0`, stack reconstruido y sin mocks. El E2E también confirmó que sesión e iteración conservan la versión activa del objetivo. La generación de una propuesta real queda **bloqueada** porque el stack no configura modelo/proveedor LLM; el escenario verifica selección y cierre seguro, no la ejecución completa del especialista.

### Desvíos del modelo de datos propuesto

- No se añadieron tablas ni índices. La propuesta se conserva en `agent_packages` como candidata `PENDING_VERIFICATION`; la selección y el resultado agregado viven en `agent_iterations`/`agent_verifications`. Se añadieron `objective_id` y `objective_version` a `agent_sessions`, tal como contempla el modelo propuesto.

### Supuestos y dependencias pendientes

- Las palabras de alcance configuration/prompt/rubric/threshold/rule, vector/retrieval/embedding y model/xgboost/classifier guían el enrutamiento; áreas desconocidas caen en Biblioteca. Un estado previo no verificado prioriza Biblioteca para el siguiente experimento.
- **H10 sigue incompleto:** existen propuestas estructuradas con validación de esquema y rangos, pero faltan los ejecutores/evaluadores de dominio: preview y prueba de la versión de configuración, borradores de Biblioteca con verificadores, construcción/consulta de una generación Vector Store candidata y entrenamiento/evaluación de candidato XGBoost sobre dataset autorizado. Ninguna propuesta pendiente puede sustentar una promoción. El E2E de propuestas reales requiere un modelo/proveedor LLM configurado en el stack.
- No se modificó frontend. No se ejecutaron `make e2e-all-local` ni `make e2e-observability`; el E2E específico H10 sí se ejecutó.

### Qué necesito de A o del integrador

- **A:** sin dependencia para este trabajo backend; FP6/FP7 permanece fuera de este alcance.
- **Integrador:** revisar este primer corte y confirmar la siguiente entrega backend para completar los ejecutores B5.1–B5.4. No empezar H11 mientras H10 esté incompleto. No se creó commit ni se hizo push.

### Continuación H10 — verificación de propuesta con proveedor configurado (2026-10-20)

- El proveedor se comprobó en runtime solo por presencia de modelo/backend; no se imprimieron valores de configuración. El symlink al `config.cfg` del checkout base no fue visible dentro del montaje Docker del worktree. Para la comprobación local se copió temporalmente el archivo ignorado al worktree; se eliminará al terminar y no forma parte del diff.
- `docker exec aria-agent-worker python -c ...` con `LLMStructuredAgentGenerator` y un prompt JSON mínimo: **pasó**, respuesta no vacía y con forma JSON (no se guardó ni imprimió el contenido).
- Invocación focalizada de `OptimizerSpecialistSubagent.execute` para XGBoost en el worker con prompt activo fijado: **pasó la generación** (`proposal=True`, sin error); estado `PENDING_VERIFICATION`. Esto confirma que el proveedor puede generar una propuesta, pero también confirma que falta el evaluador del experimento.
- `make e2e-agent-h10-local`: el Playwright por nginx volvió a pasar únicamente el recorrido fail-closed. En la ejecución del worker la verificación guardó `xgboost_contract / NOT_VERIFIED / GENERATION_FAILED`; no llegó a paquete verificado. La corrida no demuestra la ruta solicitada. El escaneo de DynamoDB se limitó a `verifier`, `status` y `error_code`; no se leyeron contenidos de propuesta.
- Desacuerdo observado: la llamada directa al generador y al subagente funcionó, pero el task Celery del E2E registró `GENERATION_FAILED`. No se aisló todavía la diferencia entre ambos contextos.

**Estado en ese corte:** H10 seguía incompleto: persistían los cuatro ejecutores/evaluadores y faltaba comprobar una propuesta `PASSED` con proveedor configurado. La continuación y evidencia de cierre aparecen abajo. No se inició H11.

**Comandos adicionales y resultado:**

- `docker exec aria-agent-worker python -c '<comprobación mínima de proveedor, salida reducida a booleanos>'`: **pasó**.
- `docker exec aria-agent-worker python -c '<ejecución de especialista XGBoost, salida limitada a estado/error/métricas seguras>'`: **pasó generación**, `PENDING_VERIFICATION`.
- `docker exec aria-agent-worker python -c '<consulta de verificaciones recientes, columnas verifier/status/error_code>'`: evidencia `GENERATION_FAILED` para la iteración Celery; sin datos de caso ni contenido crudo.
- No se ejecutaron `make lint`, `make test-architecture` ni pytest en esta continuación porque no se modificó código de aplicación. El E2E específico sí se ejecutó, pero no satisface la aceptación de propuesta verificada.

### Continuación H10 — ejecutores y evaluación con proveedor (2026-10-20)

**Qué quedó hecho**

- Se añadieron ejecutores de dominio para Configuración (preview y versión candidata inactiva), Biblioteca (campos, referencias, duplicados, PII y playbook, sin escribir entidades activas), Vector Store (generación aislada y búsqueda autorizada) y XGBoost (dataset del baseline, entrenamiento de candidato inactivo y comprobación de informe/particiones/métricas).
- El worker inyecta esos ejecutores a los cuatro especialistas. La salida verificada se persiste como paquete `VERIFIED`; solo `PASSED` sin error marca `experiment_verified=true`.
- Se corrigió la serialización de `Decimal` en el objetivo cargado desde DynamoDB. Se normaliza `budget.seconds` antes del polling del entrenamiento y se registra únicamente el tipo de excepción en caso de error.
- El E2E por nginx con proveedor real terminó el flujo principal: fijó objetivo, seleccionó XGBoost, recibió del proveedor una propuesta, entrenó y verificó un modelo candidato, canceló la sesión y comprobó la evaluación de hipótesis. No se activó el candidato.

**Diff y archivos añadidos o modificados en esta continuación**

- `src/application/ports/agent_specialist_executor_port.py`
- `src/infrastructure/agents/optimizer_specialist_executors.py`, `src/infrastructure/agents/specialist_executor_factory.py`, `src/infrastructure/agents/optimizer_specialist_subagent.py`, `src/infrastructure/agents/factories.py`, `src/infrastructure/agents/llm_structured_agent_generator.py`
- Prompts versionados: `agent.specialist.{configuration,library,vector_store,xgboost}.txt`
- `src/application/use_cases/agent/orchestrate_agent_iteration.py`
- `tests/test_infrastructure/test_agents/test_optimizer_specialist_subagent.py`, `tests/test_infrastructure/test_agents/test_optimizer_specialist_executors.py`
- `scripts/e2e_agent_h9_local.mjs` (el target H10 sigue usando el E2E Playwright común)
- `docs/handoff/HANDOFF-B.md`

**Comandos y resultado real**

- `RUFF_CACHE_DIR=/tmp/aria-h10-ruff-cache make lint`: **pasó**, Ruff 0/0 y mypy 0/0.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test make test-architecture`: **pasó**, 240/240. Pytest emitió advertencia al no poder crear `.pytest_cache` en el worktree; no fallaron pruebas.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest -p no:cacheprovider tests/test_infrastructure/test_agents/test_optimizer_specialist_subagent.py tests/test_application/test_use_cases/test_orchestrate_agent_iteration.py`: **pasó**, 21/21.
- `make e2e-agent-h10-local`: la primera repetición funcional imprimió el resultado Playwright exitoso, pero Make devolvió error al intentar limpiar un lock tomado por otro proceso. Se esperó a que el proceso de A liberara el lock y se ejecutó el target de nuevo; Playwright volvió a imprimir `H10 Playwright por nginx: objetivo fijado, propuesta XGBoost generada y verificada, cancelación e hipótesis evaluada pasaron.` Esta última ejecución no reportó error de limpieza.
- `docker exec aria-api python -c ...` (lectura filtrada de ejecución): antes del arreglo se confirmó candidato `TRAINING`; una evaluación focalizada del candidato `READY` pasó con estado `PASSED` y métricas agregadas. No se imprimieron datos de filas.
- No se ejecutó `make lint-baseline`, porque los baselines no crecieron. Tampoco se ejecutaron `make e2e-all-local` ni `make e2e-observability`.

**E2E: pasó**

La repetición final del target usó Playwright, `http://localhost` a través de nginx, API same-origin `/api/v0`, worker Celery y el proveedor LLM configurado. La propuesta XGBoost entrenó y quedó verificada; la sesión se canceló y liberó el reclamo. La primera corrida tuvo una interferencia de lock en limpieza, pero la repetición posterior terminó sin ese error. El lock quedó libre para la corrida de A.

**Desvíos del modelo de datos propuesto**

- No se añadieron tablas ni índices. El paquete existente ahora puede tener estado `VERIFIED`; conserva el contenido y la salida agregada del ejecutor. La versión candidata de configuración/modelo/Vector Store permanece inactiva o aislada.
- Para idempotencia, las versiones candidatas usan una clave derivada de sesión e iteración. En Vector Store se crea una instancia distinta y no se promueve la instancia activa.

**Supuestos y pendientes**

- Los ejecutores producen versiones candidatas o borradores; no activan modelos/configuraciones ni escriben entidades de Biblioteca en vivo. La activación y confirmación auditada siguen siendo etapas posteriores.
- El verificador XGBoost exige dataset igual al baseline autorizado, informe con particiones training/validation/calibration, hash del dataset, selección de umbral por `validation_f1` y candidato inactivo. La partición final nunca selecciona umbral.
- El E2E real cubre la ruta XGBoost. Cuatro pruebas focalizadas adicionales cubren los validadores de configuración, Biblioteca, Vector Store y XGBoost.
- El archivo `config/local/config.cfg` se copió temporalmente para montar las credenciales del proveedor en Docker; es ignorado y no forma parte del diff. **Eliminarlo al terminar la última corrida E2E**.

**Qué necesito de A o del integrador**

- **A:** ninguna dependencia para H10 backend.
- **Integrador:** revisar H10. Las rutas de los cuatro especialistas están ejecutadas y evaluadas; no se inició H11.

### Verificación final H10 (2026-10-20)

- `RUFF_CACHE_DIR=/tmp/aria-h10-ruff-cache make lint`: **pasó**, Ruff 0/0 y mypy 0/0.
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test make test-architecture`: **pasó**, 240/240 (pytest avisó que el worktree no permite crear `.pytest_cache`; las pruebas terminaron correctamente).
- `API_V0_STR=/api/v0 GENAI_ENVIRONMENT=test pytest -p no:cacheprovider tests/test_application/test_use_cases/test_create_agent_session.py tests/test_application/test_use_cases/test_orchestrate_agent_iteration.py tests/test_infrastructure/test_agents/test_optimizer_specialist_subagent.py tests/test_infrastructure/test_agents/test_optimizer_specialist_executors.py tests/test_infrastructure/test_persistence/test_agent_session_repository.py tests/test_infrastructure/test_agents/test_stub_subagent.py tests/test_infrastructure/test_entrypoint/test_agent_schemas.py tests/test_infrastructure/test_agents/test_prompt_dynamodb_mapping.py`: **pasó**, 33/33.
- `make e2e-agent-h10-local`: Playwright real por nginx con proveedor configurado: **pasó** propuesta XGBoost verificada, cancelación y evaluación de hipótesis; la repetición final no reportó error de lock.
- `git diff --check`: **pasó**.
- **Estado final:** H10 está implementado y listo para revisión; no se inició H11. No se creó commit ni se hizo push. El archivo ignorado `config/local/config.cfg` temporal ya fue eliminado.

### Revisión integradora de regresiones (2026-10-20)

- La suite completa `make e2e-all-local` pasó 27/27 por nginx tras corregir los
  fallos de E01, E05 y E06. El backend ahora usa valores Python nativos en la
  transacción de activación y define `:pending` en la aprobación del pedido.
- Lint Ruff/mypy 0/0, arquitectura 240/240 y pytest focalizado 22/22 pasaron;
  los baselines no crecieron.

### Cierre integrador H10 (2026-10-20)

- El trabajo se registró en `9fd9af6` (`DEMLGENAIF-141 feat(agent): execute
  optimizer specialists`) y se integró con FP4/FP5 en el merge `3451384`.
  El único conflicto fue `AgentSessionResponse`: quedó con `scope` de FP4/FP5
  y `objective_id`/`objective_version` de H10. No hubo crecimiento de baseline.
- En la rama integrada pasaron `make lint` (Ruff 0, mypy 0),
  `make test-architecture` (240/240) y pytest focalizado (35/35; una
  advertencia deprecada de Starlette). `git diff --check` pasó.
- `make e2e-agent-h10-local` reconstruyó API/worker y pasó por nginx con
  proveedor configurado: objetivo fijado, propuesta XGBoost generada y
  verificada, cancelación e hipótesis evaluada.
- `make e2e-observability` pasó 1/1. La suite completa registró 19 pasadas,
  7 fallidas y 1 omitida: aserción de métricas de esquema; E11 respaldos,
  E01 login, E04 login, E03 entidades y E06 login con HTTP 500; E05 no encontró
  `/private/tmp/aria-e04-partitions/e04_actual_sanitized_900.csv`. H10 y FP4/FP5
  pasaron en las corridas enfocadas y dentro de la suite. Una repetición
  enfocada confirmó un fallo de tokenizer por DNS al crear taxonomías; las
  causas de los demás HTTP 500 no están confirmadas. Mantener H11 en espera
  hasta investigar los fallos restantes.

### Contrato API propuesto H11 para A — 2026-10-20

Para que FP6/FP7 pueda avanzar sobre contratos estables, propongo conservar
el prefijo `/api/v0/agent` y el ownership ya aplicado por sesión:

- `GET /sessions/{session_id}/iterations` conserva la respuesta existente.
- `GET /sessions/{session_id}/experiments?limit=50` devuelve una lista de
  `{session_id,experiment_id,iteration_number,kind,status,created_at,
  completed_at,components,baseline_components,objective_id,objective_version,
  global_evaluation,error_code}`. Los dos conjuntos contienen pins
  `{component,entity_id,version,content_sha256}`; `kind` es `ISOLATED` o
  `COMBINATION`. La evaluación compara los candidatos con los pins baseline.
- `global_evaluation` expone `{status,minimum_protected_segment_size,global,
  baseline_global,segments,constraints}`. Cada constraint incluye
  `{constraint_id,status,aggregate,minimum_sample_size}`. Un segmento con
  soporte bajo queda fuera de `segments`, no aparece por nombre en el fallo y
  no revela su cuenta. Sólo se publican agregados con al menos 30 casos por
  segmento; se aplica el umbral mayor entre 30 y el del objetivo versionado.
- `GET /sessions/{session_id}/experiments/{experiment_id}` devuelve el mismo
  objeto o `404 {detail:{code:"EXPERIMENT_NOT_FOUND"}}`. Combinaciones
  candidatas usan estado `REJECTED_GLOBAL_CONSTRAINT` cuando cualquier
  restricción global falla; de otro modo `SUCCEEDED`/`FAILED`.
- Estados de iteración conservan `RUNNING`, `SUCCEEDED`, `STOPPED`, `FAILED`;
  sesiones mantienen sus estados existentes. No hay aprobación intermedia.
  Promoción sigue siendo una operación separada del flujo existente y exige
  `manager` o `release_manager`.
- Duración y coste son agregados de la iteración/experimento. Auditoría OTLP
  usa spans `agent.session`, `agent.iteration`, `agent.specialist` y
  `agent.tool`, con estado, duración y coste; ids de sesión/iteración,
  nombres de herramientas, versiones, filas y valores de negocio no serán
  atributos de métricas ni dimensiones de cardinalidad.

Esta propuesta se compartió antes de modificar rutas. Se implementaron las
dos lecturas de experimentos sobre ese contrato; la respuesta de iteraciones
existente no se alteró.

## H11 — estado vigente consolidado — 2026-10-21

> Esta sección sustituye los estados provisionales H11 anteriores. H11 quedó
> conectado al loop autónomo y verificado en el stack local. El resultado de un
> experimento no activa ni promueve el modelo en producción.

### Decisión versionada de etiquetas

- El objetivo global fija `knowledge_decision_policy=evidence_only_v1` en cada
  versión. Biblioteca y Vector Store entregan evidencia y su cantidad agregada;
  nunca alteran las etiquetas binarias ni el cálculo de precision/recall. Una
  política futura que permita cambiar etiquetas requiere una versión nueva del
  objetivo y nuevas pruebas comparables.
- El modelo fijado produce el score. La configuración fijada aplica el umbral
  del primer segmento habilitado que coincide con la fila. Si no hay segmentos
  habilitados, rige el umbral del bundle del modelo fijado. Si hay segmentos
  habilitados pero ninguno coincide, el scorer falla cerrado.

### Camino productivo implementado

- Al crear una sesión de optimización se guardan pins estructurados de modelo,
  configuración, Biblioteca y Vector Store. El resolver persistente recupera
  cada revisión y valida SHA-256. El modelo usa artefactos
  `models/sha256/<digest>.joblib`; revisiones actuales de Biblioteca se archivan
  antes de crear el pin.
- La salida verificada del especialista puede producir el stack candidato
  estructurado. El loop Celery compone `PairedAgentExperimentRunner` con el
  `MCPResolvedAgentPipelineScorer` y llama `EvaluateAgentExperiment` al cerrar
  la iteración. La factory inyecta también la auditoría DynamoDB.
- Baseline y candidato resuelven los cuatro componentes y se puntúan sobre las
  mismas filas de la partición final de un snapshot maduro. El snapshot guarda
  el SHA-256 de la representación CSV ya persistida; el evaluador vuelve a
  calcularlo y valida los conteos antes de puntuar. El bootstrap pareado usa
  semilla derivada del hash del snapshot y la métrica.
- La auditoría persistida incluye sesión, iteración, especialista, herramienta,
  experimento y adquisición/liberación de lease. La API de auditoría acepta
  `xgboost` y devuelve los eventos reales del loop.
- El evaluador suprime segmentos cuyo soporte sea menor que
  `max(30, minimum_support_per_segment)`. La prueba unitaria verifica el caso
  con 29 filas; el E2E integrado también comprueba 29/30 en la partición final.
- Diagnóstico del `CreatedDayIdx`: el índice está `ACTIVE` y una escritura de
  prueba sí aparece en la consulta. El 0/3000 se originaba antes: el fixture
  leía `schema_mapping` del objetivo activo en lugar del mapping del sampler;
  además, tras corregir ese mapping mantenía el conjunto de campos reservados
  anterior y elegía `event_id` como estrato. Ese campo se sobrescribe con la
  marca inicial constante. El fixture ahora lee el endpoint de mapping del
  sampler y recalcula los campos reservados después de actualizarlo.

### Qué corre en el stack y qué usa fakes

- **Camino integrado real local:** API, Celery, DynamoDB Local, MinIO, MCP,
  modelo XGBoost entrenado y Playwright a través de nginx en `http://localhost`
  con tráfico same-origin `/api/v0`. No se mockea la API en el navegador. El
  fixture de alertas es sintético y solo pertenece al stack local.
- **Solo pruebas unitarias con fakes:** supresión explícita de una etiqueta de
  segmento con soporte 29 y fallos de validación de pins/evidencia. Estas
  pruebas complementan el E2E; no se presentan como ejecución productiva.
- Un estado de experimento `SUCCEEDED` significa que pasó las restricciones
  del objetivo fijado. No cambia el modelo activo ni equivale a un despliegue,
  una aprobación de promoción o evidencia de datos productivos.

### Evidencia del E2E real — 2026-10-21

`make e2e-agent-global-pipeline-local` creó por nginx una muestra madura con
3.000 alertas elegibles y una partición final de 296 filas etiquetadas; entrenó
baseline y candidato reales. Después, `make e2e-agent-h9-local` ejecutó el loop
H11 por nginx y comprobó el experimento persistido:

- Estado `SUCCEEDED`; pins candidatos y baseline para
  `configuration`, `library`, `model` y `vector_store`.
- Partición `final`, snapshot
  `415a74293d1f826c0997a59acf235d20`, SHA-256
  `67d806d21c920df8d7a34b92cdb338129fef53ecc9bc201351fc06bf4fa4a972`.
- Política `evidence_only_v1`; categorías de auditoría observadas:
  `experiment`, `iteration`, `lease`, `session`, `specialist`, `tool`.
- `candidate_active=false` tras el éxito del experimento.

Es evidencia de integración en el stack local con datos sintéticos, no de
producción ni de promoción. El primer E2E aislado no tenía snapshot final; el
siguiente encontró una composición incorrecta del runner; la ejecución que
produjo la evidencia anterior pasó con el hash reproducible, scorer compuesto y
auditoría conectada.

La repetición con la frontera 29/30 sembró 3.000 alertas elegibles y 283 filas
etiquetadas en la partición final. El flujo de preparación H8 y el E2E H11 se
ejecutaron por nginx contra el stack local; el runner comparó el modelo y la
configuración fijados junto con Biblioteca y Vector Store, sobre el mismo
snapshot:

- Estado `SUCCEEDED` de evaluación local, snapshot
  `ee2a1ca652f851b5c86c8a5968d789cf`, SHA-256
  `d08d0e2783ef4b0df55ef229b7a68bd5b799c0ad868614aeb546189fbd0a7862`.
- Segmentos: `event_type_E2E_SUPPORT_30` publicado con soporte 30;
  `E2E_SUPPORT_29` no publicado. El E2E exige ambos resultados y falló antes
  cuando el fixture no generaba segmentos, en vez de aceptar un mapa vacío.
- Política `evidence_only_v1`; eventos reales de auditoría
  `experiment`, `iteration`, `lease`, `session`, `specialist`, `tool`; UI mostró
  sesión, iteración, herramienta, lease y experimento. `candidate_active=false`.
- `make e2e-agent-h11-local` no terminó su etapa de build en el último intento
  por una descarga/decodificación transitoria de Poetry desde PyPI. Para obtener
  la evidencia se ejecutaron directamente el sembrado H8 y Playwright H11 por
  nginx sobre el stack local levantado, con las imágenes backend ya reconstruidas.

Este resultado sigue siendo local y usa datos sintéticos: `SUCCEEDED` no equivale
a despliegue ni promoción productiva.

### Verificaciones

- `make lint`: Ruff y mypy, 0 errores; baseline en cero.
- `make test-architecture`: 246/246.
- Pruebas focalizadas de runner, evaluador y persistencia: 21/21.
- `git diff --check`: sin errores.
- E2E real por nginx: se validaron el snapshot, los cuatro componentes,
  scoring reproducible, supresión de soporte 29 y publicación de soporte 30.
- **Estado H11:** cerrado por decisión del usuario el 2026-10-21. La evidencia
  local `SUCCEEDED` no activa el candidato ni equivale a despliegue o promoción
  productiva; el flujo de liberación gradual corresponde a H12.

No se creó commit ni se hizo push.

### Datos de entrenamiento y Excel de modus operandi — 2026-10-21

Revisé `/Users/davidrojas/Downloads/Modus Operandi.xlsx`. Las hojas `Digital`
y `Tarjetas` describen señales/reglas por canal; las hojas `Diccionario ...`
aportan catálogos, entre ellos integration points y canales digitales. Los dos
diccionarios de Integration Point aparecen duplicados. `Diccionario EventTypes`
y `Diccionario Triggered Rules` no contienen valores aparte de sus encabezados.
La hoja no debe cargarse como si fuera un dataset etiquetado de entrenamiento.

El snapshot de entrenamiento ahora construye predictores solo con campos del
esquema que no sean sensibles ni estén marcados como etiqueta, y excluye
además los campos configurados para marca inicial, fecha inicial de marca,
fecha de última marca y objetivo. La única columna de resultado que se guarda
para entrenar es `fraud_label`; el mapeo de marcas sigue usándose internamente
para elegir alertas maduras y derivar esa etiqueta. El snapshot registra la
lista de campos excluidos para poder auditar la separación.

La separación evita que decisiones de marcación posteriores se conviertan en
predictores. Las reglas del Excel que usan expresiones como “sin marcación
fraude” o describen hechos “previos o posteriores a la transacción fraude”
requieren una definición temporal/as-of antes de convertirse en features; no
se deben importar literalmente como señales de entrenamiento.

Validación focalizada: `tests/test_application/test_use_cases/test_create_mature_sample_snapshot.py`
comprueba que las marcas y otras etiquetas del esquema no aparecen en las filas
de entrenamiento y que `fraud_label` es el target. El E2E global se ejecutó
por nginx el 2026-10-21: 3.000 alertas elegibles,
2.991 de tamaño estimado y 280 filas etiquetadas en la partición final;
baseline y candidato quedaron comparados sobre esa partición. `make lint`
pasó (Ruff/mypy 0), arquitectura 251/251 y la prueba focalizada 1/1. El stack
local se apagó después de la corrida y el lock quedó liberado. La suite completa
de Playwright no se ejecutó: este cambio afecta la construcción de snapshots,
y se corrió el E2E global que crea y consume esa muestra.

### Reintento acotado de llamadas LLM — 2026-10-22

El adaptador compartido `LangchainChatModelUnitOfWork` ahora reintenta una vez
ante fallos transitorios del proveedor (conexión, timeout, HTTP 429/5xx y
códigos transitorios de Bedrock), con espera de 250 ms. Errores no transitorios
siguen fallando de inmediato. El span registra cantidad de reintentos/intentos
y tipo de error, sin persistir el mensaje del proveedor.

Pruebas del adaptador y consumidores: 10/10; `make lint` (Ruff/mypy 0/0) y
`make test-architecture` (251/251) pasaron. `make e2e-agent-h11-local` pasó
por nginx: H8 evaluó 316 filas etiquetadas y H11 terminó `SUCCEEDED`; su
escenario H9 confirmó los campos de diagnóstico en la API. La corrida no
inyectó un error transitorio, por lo que valida la integración, no el camino
de reintento en el proveedor real. El stack se apagó al terminar.

### Reanudación del diagnóstico H11 — 2026-10-23

Se conservaron los artefactos locales y se repitió el smoke con 3 workers.
Primer intento: H8 reservó 36 filas finales de 360 elegibles; H11 terminó con
`GLOBAL_EVALUATION_FAILED`. Los 36 workflows quedaron persistidos: 9
`SUCCEEDED`, 27 `FAILED`, mayormente por objeciones adversariales sobre scores
sin calibrar, señales ARIC nulas y uso de `retail` como contraparte.

Segundo intento: como no se borraron los fixtures anteriores, el muestreador
vio 720 alertas elegibles y reservó 61 filas finales. H11 volvió a fallar;
27 workflows `SUCCEEDED` y 34 `FAILED`. El revisor identificó además que el
perfil determinista no separaba explícitamente el score BioCatch de los flags
ARIC, que la ausencia de cambios reportados podía leerse como ausencia de
cambios, y que `approved` no verifica legitimidad. El código ahora separa
esas evidencias, evita inferir recurrencia de beneficiario desde `retail` y
añade criterios simétricos al prompt adversarial. Los códigos seguros de
fallo del scorer se conservan (`PIPELINE_REPLAY_WORKFLOW_FAILED`) sin guardar
mensajes de excepción ni payloads.

Pruebas focalizadas actuales: 47/47; `make lint`: Ruff/mypy 0/0, baseline 0;
`make test-architecture`: 253/253. El segundo E2E se construyó antes de la
última precisión de la narración sobre flags, estados históricos y cambios
reportados, por lo que esas correcciones aún requieren una nueva verificación
E2E. H11 no se declara verificado por esta repetición fallida. Los registros
de ambas corridas se conservaron; el stack quedó restaurado a una réplica del
worker de test y configuración normal.

### Reanudación del trabajo — 2026-10-23

Se repitió H9 sobre el snapshot ya existente de 61 alertas, sin sembrar ni
eliminar datos. En DynamoDB local quedaron 29 workflows `SUCCEEDED` y 32
`FAILED`; el experimento terminó con `PIPELINE_REPLAY_WORKFLOW_FAILED`. Los
errores detallados muestran tres patrones que la narración y los prompts aún
deben resolver: (1) reviewers y clasificadores confunden scores disponibles
pero no calibrados con ausencia de señales, y flags ARIC nulos con señales
limpias; (2) asocian `retail` o tres transacciones `approved` con recurrencia o
legitimidad; (3) omiten o no ponderan una hora exacta repetida en varias fechas
y una fecha de modificación sin detalle. El perfil determinista ahora expone
la fecha de modificación, califica la muestra como rango observado y narra la
hora repetida como un patrón a revisar; los prompts del clasificador y revisor
se reforzaron para mantener esas distinciones.

El script Playwright detectó `fetch failed` al restaurar settings mediante
`fetch` de Node directo y dejó el proceso de navegador abierto. Se corrigió la
limpieza para usar el proxy same-origin `/api/...` del navegador y cerrar el
navegador aun si una restauración falla. Se restauraron los valores previos de
settings (optimizador apagado, máximo 5 sesiones, cero renovaciones) mediante
el repositorio y se registró la restauración en auditoría. No se borró ningún
workflow, snapshot o sesión. El stack volvió a un worker de test y
`E2E_PRESERVE_DATA=0`.

Después de los cambios, pruebas focalizadas: 50/50; `make lint`: Ruff/mypy 0/0,
baseline 0; `make test-architecture`: 253/253; `node --check` y
`git diff --check` limpios. El E2E no pasó y no se repitió tras los últimos
cambios de prompts; no se declara H11 verificado.

### Estado corregido de la reanudación — 2026-10-23

La corrida H9 lanzada sobre el snapshot preservado de 61 alertas terminó con
37 workflows `SUCCEEDED` y 24 `FAILED`. Playwright salió con
`page.evaluate: TypeError: Failed to fetch` durante la restauración final de
settings; por eso ese E2E no pasó, aunque los workflows terminaron después.
Actualicé la corrida a `FAILED`, el experimento y la iteración a `FAILED` con
`PIPELINE_REPLAY_WORKFLOW_FAILED`, y cancelé la sesión mediante el caso de uso
auditado. Los 61 workflows, el snapshot y sus evidencias siguen preservados.
El optimizador quedó apagado, con máximo 5 sesiones y 0 renovaciones; la cola
de test está en una réplica y el frontend sigue arriba.

El perfil determinista ahora acepta roles de esquema `biocatch_score`,
`model_score` y `max_amount_*` aunque cambien los nombres fuente. Para los
máximos legados usa el nombre del campo seleccionado como etiqueta, sin
depender de un catálogo fijo de columnas fuente. Verificación tras el cambio:
51 pruebas focalizadas, Ruff/mypy 0/0, arquitectura 253/253 y
`git diff --check` limpio. Sigue pendiente validar el comportamiento con un
E2E real pequeño; no se repitió el H9 de 61 alertas.

El endpoint de cola `GET /api/v0/analyst-queue/in-process` respondió por nginx
en `http://localhost` (401 sin autenticación), confirmando que la ruta está
disponible. No corrí `analyst-queue-real.spec.ts`: faltan las cuatro variables
`E2E_MANAGER_*` y `E2E_FRAUD_ANALYST_*`; el stack tampoco se reconstruyó después
de los últimos cambios de perfil. No modifiqué ni limpié el workspace frontend.

### Smoke H8 preservando datos — 2026-10-23

Reconstruí solo API, MCP y los workers backend necesarios; el worker de test se
quedó en una réplica. El E2E H8 por nginx se lanzó con
`E2E_AGENT_FAST=1 E2E_PRESERVE_DATA=1`, de modo que no se borraron fixtures ni
artefactos previos. El fixture agregó 360 alertas sintéticas, pero el muestreador
encontró 1.079 alertas elegibles y evaluó 101 filas etiquetadas en la partición
final al combinar datos preservados. H8 terminó `SUCCEEDED`.

No inicié H9: la muestra efectiva no era de aproximadamente 30 casos, como se
había pedido. El intento anterior con `poetry run` no aplicaba porque este repo
no tiene `pyproject.toml`; el comando ejecutado con éxito fue
`python -u scripts/e2e_global_pipeline_local.py`. API y nginx quedaron sanos,
los workers reportaron cero tareas activas/reservadas y los ajustes mutables
fueron restaurados por el `finally` del guion. Los registros sintéticos nuevos,
el snapshot y los modelos de esta corrida se conservaron. El próximo paso es
aislar una muestra de 30 sin limpiar datos existentes y recién entonces correr
el Playwright H9.
