# Especificación delegable: E2E completo de gobierno del esquema de alertas

## Objetivo

Completar la cobertura E2E real de las tareas C1–C6 del documento
`docs/ALERT_SCHEMA_GOVERNANCE.md`, usando Playwright contra la plataforma
local completa y la API real expuesta por nginx.

El trabajo debe partir del mapeo ya construido en:

- `../frontend_mockup/e2e/alert-schema-real-api.spec.ts`
- `../frontend_mockup/e2e/fixtures/muestra_total_aria_head5.csv`

Si durante la ejecución se detectan campos incorrectos o incompatibilidades,
se ajusta el seed y se documenta el cambio. No se debe relajar la
obligatoriedad de los siete roles del sistema para hacer pasar una prueba.

## Decisiones ya tomadas

- El flujo de propuestas de esquema permanece separado de
  `configuration-deploy-requests`.
- Los commits existentes se consideran realizados.
- No se requiere resolver la limpieza o migración de datos históricos para
  esta delegación.
- El E2E usa `http://localhost` y nginx; no debe llamar directamente al API
  en `localhost:8000`.
- La limpieza E2E se hace exclusivamente mediante el endpoint protegido de
  la API. No usar conexión directa a DynamoDB.
- El estado previo requerido es limpio, excepto los usuarios E2E.
- El fixture reducido contiene cinco registros sintéticos consistentes y el
  caso candidato procesa las cinco filas con la cola real de workers.
- Las credenciales se reciben mediante variables de entorno; nunca se
  escriben en código, fixtures, logs ni documentación.

## Seed base requerido

Crear un seed idempotente reutilizable por todos los escenarios, idealmente
como:

```bash
make e2e-seed \
  E2E_MANAGER_EMAIL="$E2E_MANAGER_EMAIL" \
  E2E_MANAGER_PASSWORD="$E2E_MANAGER_PASSWORD" \
  E2E_RELEASE_MANAGER_EMAIL="$E2E_RELEASE_MANAGER_EMAIL" \
  E2E_RELEASE_MANAGER_PASSWORD="$E2E_RELEASE_MANAGER_PASSWORD"
```

El seed debe ejecutarse por API y debe:

1. Autenticar `manager` y `release_manager`.
2. Crear o reutilizar una versión base del esquema.
3. Proponerla con `manager`.
4. Aprobarla con `release_manager`.
5. Dejar una versión candidata propuesta para pruebas de impacto.
6. Crear o reutilizar la configuración activa necesaria.
7. Cargar y analizar el fixture de cinco filas.
8. Devolver o persistir los ids/versiones necesarios para los escenarios.

Debe ser seguro ejecutarlo varias veces después de `make e2e-clean` y no debe
crear duplicados arbitrarios de esquemas, datasets o configuraciones.

## Mapeo inicial del esquema

El seed debe usar inicialmente el mapeo completo ya definido en
`completeMappedFields` y `mandatoryFields` del E2E real.

### Roles requeridos en el esquema

Los siete roles deben tener asignación en el esquema. Por transacción,
`amount` puede faltar sin escalar la alerta; los otros seis roles siguen
siendo obligatorios.

| Rol | Ubicación CSV | Tipo |
| --- | --- | --- |
| `event_id` | `eventid` | `string` |
| `event_time` | `fecha_transaccion` | `datetime` |
| `event_type` | `eventtype` | `string` |
| `channel` | `channel` | `string` |
| `entrypoint` | `integrationpoint` | `string` |
| `amount` | `amount_value` | `number` |
| `customer_id` | `customerid` | `string` |

### Labels de evaluación

Estos valores deben permanecer fuera del input enviado a los agentes:

- `marcacion_final`
- `razon_marcacion`
- `tipo`
- `output_tags`

`output_tags` se usa como label solo para entrenamiento/evaluación de
entrenamiento; no es un label operativo de la alerta en producción. En ambos
casos permanece fuera del input enviado a los agentes.

### Campos opcionales

El mapeo existente cubre también:

- `reviewstatus_first`;
- scores de Biocatch y `Model_score`;
- indicadores de dispositivo/Biocatch;
- `deviceid`, `transactionid` y reglas disparadas;
- datos de cliente y documento;
- ciudad, contacto y fechas de cliente;
- montos históricos `MontoMasAlto*`;
- `transacciones_json` y `alertas_json`.

Los campos opcionales pueden estar ausentes en el fixture reducido y no deben
provocar escalación por datos obligatorios faltantes.

## Escenarios requeridos

### C1 — Gobierno completo

Verificar con Playwright y API real:

- Configuración → Esquema y sus cuatro subpestañas.
- Visualización de versión activa, propuesta e historial.
- Propuesta por `manager`.
- Aprobación por `release_manager`.
- Aprobación propia bloqueada.
- Aviso de impacto de la propuesta.
- Evento original enmascarado según sensibilidad.
- Registro de auditoría y permisos por rol.

### C2 — Procesamiento de alertas

Crear alertas mediante el flujo real disponible y verificar:

- payload crudo en almacenamiento de objetos;
- alerta canónica con `input`, `labels`, `history_prev_alerta` y
  `agent_output`;
- cola y detalle dirigidos por esquema;
- formatos regionales y valores faltantes;
- historial;
- evento original restringido y auditado;
- exportación “Al dataset”.

### C3 — Métricas

Procesar alertas con la v1 activa y verificar por API/UI:

- dimensiones `channel`, `entrypoint` y `amount` tomadas desde roles;
- `schema_version` en snapshots y métricas;
- separación entre métricas de versiones distintas;
- dashboard sin depender de nombres físicos de columnas.

### C4 — Testing con esquema candidato

El escenario actual ya cubre parte de este caso. Completarlo verificando:

- cinco filas procesadas;
- comparación `active` vs `candidate`;
- campos agregados, modificados y retirados;
- roles modificados;
- labels separados del input;
- ningún prompt recibe `tipo`, `marcacion_final` u otro label.

### C5 — Análisis diario

Ejecutar el job de presencia y validar:

- reporte diario persistido;
- presencia por campo y ubicación;
- distribución de roles;
- sugerencias de esquema;
- campos de sistema;
- acceso restringido a los roles permitidos.

### C6 — Simulador

Verificar:

- siembra desde el dataset;
- generación de valores conforme al esquema activo;
- distribución de campos categóricos;
- generación numérica;
- sustitución sintética de campos sensibles;
- exclusión de labels y datos de desenlace del evento generado.

## Reglas técnicas

- Preferir assertions de API para estados asíncronos y usar UI para validar
  navegación, visibilidad y permisos.
- Esperar operaciones asíncronas mediante sus endpoints de polling; no usar
  sleeps fijos como mecanismo principal.
- Cada prueba debe poder ejecutarse después de la limpieza E2E.
- No usar mocks ni interceptar `/api/v0` en la suite real.
- Mantener una suite simulada separada para pruebas rápidas de UI.
- No modificar la base compartida ni usar credenciales hardcodeadas.
- Si falla por una diferencia de contrato, corregir el contrato o el seed y
  añadir una prueba regresiva; no eliminar validaciones del dominio.

## Criterios de aceptación

La delegación se considera terminada cuando:

- existe un `e2e-seed` idempotente documentado;
- C1–C6 tienen al menos un escenario real automatizado;
- `make e2e-clean` funciona por API;
- `make e2e-real` ejecuta el seed y la suite sin conexión directa a DB;
- los escenarios principales pasan con dos usuarios distintos;
- los labels nunca aparecen en inputs/prompts de agentes;
- el reporte final incluye comandos ejecutados, cobertura y cualquier campo
  ajustado del seed;
- no quedan secretos ni datos productivos en el repositorio.

## Comandos de validación

```bash
make e2e-clean \
  E2E_MANAGER_EMAIL="$E2E_MANAGER_EMAIL" \
  E2E_MANAGER_PASSWORD="$E2E_MANAGER_PASSWORD"

make e2e-seed \
  E2E_MANAGER_EMAIL="$E2E_MANAGER_EMAIL" \
  E2E_MANAGER_PASSWORD="$E2E_MANAGER_PASSWORD" \
  E2E_RELEASE_MANAGER_EMAIL="$E2E_RELEASE_MANAGER_EMAIL" \
  E2E_RELEASE_MANAGER_PASSWORD="$E2E_RELEASE_MANAGER_PASSWORD"

E2E_BASE_URL=http://localhost make e2e-real \
  E2E_MANAGER_EMAIL="$E2E_MANAGER_EMAIL" \
  E2E_MANAGER_PASSWORD="$E2E_MANAGER_PASSWORD" \
  E2E_RELEASE_MANAGER_EMAIL="$E2E_RELEASE_MANAGER_EMAIL" \
  E2E_RELEASE_MANAGER_PASSWORD="$E2E_RELEASE_MANAGER_PASSWORD"
```

## Entrega esperada del agente

- Implementación del seed y targets `make`.
- Especificaciones Playwright para C1–C6.
- Fixtures mínimos y documentación de campos ajustados.
- Evidencia de ejecución exitosa.
- Lista de archivos modificados y limitaciones conocidas.

## Estado de ejecución (2026-10-13)

Implementado:

- `make e2e-clean` elimina datos E2E mediante la API autenticada en nginx y
  reinicia API/worker desde Make. Los usuarios y volúmenes se preservan.
- `make e2e-seed` crea o reutiliza v1 activa, v2 propuesta, configuración
  `default` y el dataset E2E por API. Si el dataset existe, lo elimina por API,
  espera el borrado y vuelve a cargar el fixture actual.
- `make e2e-real` con `E2E_FROM=0` (default) encadena limpieza, seed,
  Playwright real y análisis diario; `E2E_FROM=1..6` conserva el estado y
  omite los pasos anteriores. `E2E_BASE_URL` y el default usan
  `http://localhost`.
- `make local-test-queue-purge` reinicia el worker de pruebas y purga mensajes
  pendientes de su cola `test` tras una corrida interrumpida.
- El fixture tiene cinco filas sintéticas consistentes, sin datos productivos.
  `customer_id` usa `obfuscate`; `tipo`, `marcacion_final`, `razon_marcacion` y
  `output_tags` se modelan como labels.
- La ruta de simulación entrega `SeedSimulationFromDatasetInput`; el caso de uso
  ahora acepta ese DTO y genera valores para campos opcionales ausentes.
- El workflow persiste el resultado canónico del preproceso antes de registrar
  métricas. Esto permite que el snapshot tome `schema_version` y dimensiones de
  los roles en vez de conservar `unknown` del evento de creación.

Validación final ejecutada mediante Make, con nginx en `localhost`:

```text
make e2e-real E2E_FROM=0 GENAI_ENVIRONMENT=local E2E_BASE_URL=http://localhost ...
Playwright: 6 passed (3.1m)
E2E presence: report_day=2026-10-12, schema=v2, alerts=0, fields=56, suggestions=1
```

Los seis escenarios cubren gobierno y aprobación cross-user, el lote de cinco
filas con labels fuera del input, cola/detalle con formato regional, raw y su
auditoría, historial y curación, métricas con corte de versión visible, reporte
de presencia y sugerencias, y preview del simulador sin labels. También se
verificó una reanudación desde C5 con el checkpoint persistido. El reporte marca
cero alertas porque `e2e-clean` corre antes del análisis diario. La suite no
define el resultado del agente para las filas: valida procesamiento, estado
terminal y separación de labels.

La especificación amplia de flujos UI/API sigue pendiente para los recorridos
E00–E09 (roles, biblioteca, datasets, entrenamiento, remarcación y navegación
integral del simulador); la suite C1–C6 es una cobertura específica del esquema.
