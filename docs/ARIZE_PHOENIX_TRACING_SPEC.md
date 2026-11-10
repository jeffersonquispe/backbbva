# Especificación: Arize Phoenix y trazabilidad jerárquica

Fecha: 2026-11-05  
Estado: implementado (2026-11-09), pendiente E2E real; retención por `PHOENIX_RETENTION_DAYS` (días, defecto 30)  
Macro tarea: `PENDIENTES.md` §13

## Objetivo

Incorporar Arize Phoenix como interfaz de consulta de trazas LLM y de
herramientas, con persistencia PostgreSQL (sin SQLite), aprovechando el
OpenTelemetry y el Collector existentes. La aplicación solo emite OTLP al
Collector; no conoce Phoenix, sus credenciales, su URL ni su base de datos.
El Collector distribuye las trazas a los backends configurados, incluido
Phoenix.

Las trazas deben permitir seguir cada ejecución con esta jerarquía:

```text
workflow (trace_id = workflow_execution_id)
└── operación/etapa (span nativo con span_id propio)
    ├── llamada LLM (span hijo + run_id)
    └── llamada a herramienta (span hijo + run_id)
```

## Decisiones de diseño

### Identificadores y contexto

- **`trace_id`**: el ID UUID de `workflow_execution_id`, convertido a los 128
  bits del `TraceId` de OpenTelemetry. De esta manera coincide con el ID del
  workflow ya persistido por ARIA. Se comprobará que el UUID no sea cero y que
  el contexto pueda propagarse entre procesos Celery mediante W3C
  Trace Context.
- **`span_id`**: lo genera OpenTelemetry para cada span y distingue una
  operación concreta dentro de la traza. El span de cada etapa incluye
  `aria.workflow.step_id` y `aria.workflow.step` para enlazarlo con el ID y
  nombre de etapa persistidos por ARIA. No se forzará un UUID de dominio dentro
  del campo nativo de 64 bits `span_id`.
- **`run_id`**: UUID nuevo por invocación de LLM o herramienta, representado
  como atributo `aria.run_id` en el span de esa llamada. Se conservará el mismo
  run ID durante reintentos que sean una misma ejecución lógica; un nuevo
  intento independiente recibe otro ID. Si LangChain ya proporciona un
  identificador de ejecución, se reutiliza cuando sea estable y único; de lo
  contrario se genera en el adaptador.
- Las ejecuciones sin workflow (p. ej. chat del asistente, optimizador o tareas
  administrativas) conservan un `trace_id` OpenTelemetry generado y añaden
  `aria.workflow.id` solo cuando exista una ejecución ARIA asociada.
- Trazas que ocurren después del cierre del workflow (p. ej. una revisión de
  fraude) empiezan una traza nueva y conservan `aria.workflow.id` como
  correlación; no se reabre una traza ya finalizada.

### Instrumentación

- Mantener `MonitoringPort` y el adapter OpenTelemetry como abstracción para
  la aplicación; no importar Phoenix ni el SDK de Phoenix desde `src/`.
- Crear/propagar un span raíz de workflow y spans por etapa en el runner
  Celery. Inyectar y extraer el contexto W3C en el mensaje Celery para que
  retries, cadenas y procesos worker mantengan el mismo `trace_id` y la
  relación padre-hijo adecuada.
- Añadir spans hijos para todas las llamadas reales a herramientas (incluidas
  búsqueda de Vector Store, historial, watchlist y calculadora) y llamadas a
  LLM/embeddings. Cada llamada lleva `aria.run_id`, `aria.operation.type`,
  nombre lógico de operación/herramienta, resultado y duración. Las llamadas
  ya creadas por LangChain se enriquecen/correlacionan; no se duplican.
- Registrar errores como estado y `error.type` con excepciones redactadas.
  Evitar etiquetas de alta cardinalidad salvo los identificadores de
  correlación expresamente requeridos para buscar una ejecución.
- Conservar dimensiones seguras ya definidas (`span_dimension_attributes`):
  nunca `customer_id`, monto exacto, credenciales ni notas de analistas.
  Prompts, respuestas y argumentos/resultados de herramientas siguen sujetos
  a `OTEL_CAPTURE_LLM_CONTENT=false` por defecto; no se habilita contenido
  sensible para activar Phoenix.
- Si una tarea no tiene contexto remoto válido, se crea una traza nueva y se
  adjuntan atributos de correlación disponibles. La instrumentación no debe
  cambiar el resultado del workflow si Collector o Phoenix están caídos.

### Enrutamiento y almacenamiento

- Añadir un exporter OTLP HTTP de trazas en el Collector hacia Phoenix. La app
  mantiene su exporter OTLP gRPC actual hacia el Collector. No duplicar la
  exportación directa desde cada servicio a Phoenix.
- Mantener la salida actual hacia Tempo y demás backends; Phoenix se suma como
  destino configurable del Collector. Errores de un destino no deben impedir
  que los otros reciban telemetría; configurar cola, reintentos y límites de
  memoria adecuados.
- Desplegar Phoenix con PostgreSQL mediante `PHOENIX_SQL_DATABASE_URL` y
  volumen persistente para los datos de PostgreSQL. No usar SQLite ni un
  filesystem efímero para producción. En local, Compose levanta PostgreSQL y
  Phoenix con volúmenes nombrados y health checks.
- Mantener secretos fuera de los manifiestos versionados. La URL/credenciales
  del backend Phoenix son configuración del Collector/entorno, nunca variables
  de la aplicación. OKD usará Secret + almacenamiento persistente definido por
  la plataforma.
- Establecer política de retención, backups, TLS/autenticación y exposición de
  UI según el entorno antes de producción. Phoenix local puede exponerse solo
  por el puerto documentado de desarrollo.

## Cambios previstos

1. Validar trazas raíz y los contextos activos en API, Celery y LangChain;
   diseñar propagación W3C compatible con firmas JSON de tasks.
2. Extender el adapter de OpenTelemetry para crear spans de herramientas,
   generar/reutilizar `run_id` y registrar atributos de correlación.
3. Modificar el runner y sus fábricas para instrumentar workflow/etapas sin
   romper las reglas hexagonales ni construir adapters dentro de use cases.
4. Añadir Phoenix + PostgreSQL al stack local de observabilidad y configurar el
   Collector para enrutar trazas a Phoenix y Tempo.
5. Añadir configuración/manifiestos de OKD con persistencia y secretos
   externalizados; documentar operaciones, backup, restauración y retención.
6. Actualizar las reglas de observabilidad en `CLAUDE.md` y el runbook: Phoenix
   se admite como backend alcanzado únicamente por OTLP/Collector; la app sigue
   sin dependencia directa de Phoenix.

## Criterios de aceptación

- Para un workflow real, Phoenix muestra el `trace_id` igual al UUID de
  `workflow_execution_id`; cada etapa aparece como span y conserva su `step_id`.
- Cada llamada LLM y de herramienta aparece una sola vez como span descendiente
  de la etapa correcta, con un `aria.run_id` único y consultable.
- Un retry Celery preserva la identidad de traza y expresa correctamente la
  relación de spans entre procesos.
- Una llamada posterior al workflow puede buscarse por `aria.workflow.id` sin
  alterar una traza terminada.
- Tras reiniciar Phoenix/PostgreSQL, las trazas previas siguen disponibles.
- Si Phoenix no está disponible, el resto del pipeline OTLP y el workflow
  continúan operando; no hay exportación Phoenix directa desde la app.
- Los tests verifican IDs, contexto distribuido, errores, no duplicación y
  ausencia de campos prohibidos. E2E real por el stack local valida una llamada
  LLM y al menos una herramienta.
- Se ejecutan `make lint`, `make test-architecture`, pytest enfocado,
  `make test-api-contracts` si aplica y los E2E exigidos por `AGENTS.md`.

## Riesgos y decisiones pendientes antes de producción

- Confirmar la versión de Phoenix, el formato de endpoint OTLP HTTP y los
  requisitos de autenticación/TLS vigentes en el entorno objetivo.
- Acordar tamaño y política de retención de PostgreSQL con plataforma; la
  retención de la UI no sustituye backups.
- Medir volumen y costo de cardinalidad para `aria.run_id`, workflow IDs y
  atributos LangChain; los IDs se requieren para búsquedas, pero no deben
  replicarse como dimensiones de métricas.
- Confirmar cómo transportar contexto W3C por las firmas y mensajes Celery
  actuales sin romper compatibilidad de tareas ya encoladas.

## Referencias

- [Phoenix self-hosting](https://arize.com/docs/phoenix/self-hosting/deploying-phoenix): soporta PostgreSQL con `PHOENIX_SQL_DATABASE_URL`; SQLite es el valor por defecto.
- [Phoenix tracing](https://arize.com/docs/phoenix/learn/tracing/how-tracing-works): recibe trazas mediante OTLP.
