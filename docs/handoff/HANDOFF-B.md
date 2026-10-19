# Handoff Sesión B — H3

Fecha: 2026-10-18
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
- No se creó commit ni se hizo push.

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

- **A:** H2 ya integrado en `8864dba`; no hay dependencia pendiente para cerrar H3.
- **Integrador:** revisar el handoff y resolver los conflictos de integración que encuentre. H3 queda listo para revisión; no avanzar a H4 hasta recibir aprobación.
