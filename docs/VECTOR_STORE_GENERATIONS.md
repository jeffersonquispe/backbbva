# Generaciones de Vector Store

Pendiente #30 (`PENDIENTES_MVC.md`). Regla: **construir no publica**.

## Modelo

Una instancia de Vector Store tiene dos partes:

- **Manifiesto editable**: la lista de documentos de la Biblioteca asociados a
  la instancia (`vector_store_instance_assets`). Agregar o quitar documentos no
  toca OpenSearch.
- **Generaciones inmutables** (`vector_store_generations`, PK `instance_id`,
  SK `generation`): cada carga del manifiesto en el índice `fraud_knowledge`.
  Todos sus documentos llevan `vector_store_id` + `vector_store_version`
  (= número de generación), y toda búsqueda filtra por ambos.

Estados: `building` → `ready` | `failed`; `ready` → `retired` (por retención).
Una generación nunca se edita ni se borra al construir otra.

El build calcula un **fingerprint** SHA-256 de los textos, embeddings y
relaciones que cargaría. Si ya hay una generación `ready` con ese fingerprint,
la devuelve (`built: false`) en vez de duplicarla. Usa el embedding vigente de
cada entrada de la Biblioteca; solo calcula uno nuevo si la entrada no tiene.

## Quién consulta qué

Cada herramienta de Vector Store de una configuración guarda
`vector_store_instance_id` y `vector_store_generation`.

| Momento | Qué pasa |
| --- | --- |
| Guardar una versión | Toda herramienta habilitada sin generación queda fijada a la generación del manifiesto actual (se construye si no existe). Un pin explícito debe estar `ready`. |
| Probar una versión | `POST /test-runs` responde **409** si un pin no está `ready` (retirado, fallido) o falta. Ya no corre en silencio sin RAG. |
| Activar | `POST /configurations/{id}/versions/{v}/activate` responde **409** si la versión consulta generaciones distintas de las activas. Solo `POST /configuration-deploy-requests/{id}/approve` (manager/release_manager, distinto del solicitante) las publica. |
| Producción | El worker busca la generación fijada. Si no está disponible, la búsqueda devuelve vacío, registra advertencia y `research_call` fallido (fail-open, como antes). |
| Biblioteca | `GET .../query?generation=N`; sin `generation`, la última `ready`. |

Activar exige además una prueba exitosa de **esa misma versión**, así que los
documentos probados son los que publica el despliegue.

Límite: el playbook del Analista se lee en vivo de la entrada de Modus Operandi
encontrada (`ResolveAnalystPlaybookUseCase`). La generación fija qué documentos
se recuperan, no el contenido vigente del playbook; versionar la Biblioteca
completa no es parte de #30.

## API

| Método | Ruta | Roles |
| --- | --- | --- |
| `POST` | `/vector-store-instances/{id}/generations` | manager, channel_manager, data_analyst. 200 con `built`; 422 manifiesto vacío/incompleto; 409 otra construcción en curso; 404 instancia. |
| `GET` | `/vector-store-instances/{id}/generations` | mismos roles. Más reciente primero, con `in_production`, `pinned_by` y `matches_manifest`. |
| `GET` | `/vector-store-instances` | `latest_generation` y `production_generations` por instancia. |

`POST /{id}/promote` se eliminó.

## Optimizador y H12

- El especialista de Vector Store construye una generación candidata en una
  instancia aislada `agent-<sesión>-<iteración>`; el pin del experimento es
  `(instancia, generación)`.
- El baseline toma la herramienta de Vector Store fijada en un segmento
  habilitado de la configuración activa. Si la configuración activa no usa
  Vector Store, fija la última generación lista de la instancia más reciente.
  Sin eso, el optimizador no podría abrir sesiones (exige los cuatro
  componentes), y ese pin no altera resultados: el replay solo lo aplica en
  pasos con la herramienta habilitada.
- El hash del pin usa solo datos inmutables: instancia, generación,
  fingerprint y manifiesto de la generación. Renombrar la instancia o editar su
  manifiesto no cambia un pin existente; una generación retirada deja de
  resolver.
- Un release H12 no publica el Vector Store por su cuenta. Si su configuración
  candidata fija la generación, el handoff queda `configuration_deploy_request`
  / `pending`; si no, `configuration_pin_required` / `manual`.

## Retención

Tarea `vector_store.cleanup_generations`, beat diario 04:30 Bogotá.
Variables: `VECTOR_STORE_GENERATION_CLEANUP_ENABLED` (true),
`VECTOR_STORE_GENERATION_RETENTION_DAYS` (14),
`VECTOR_STORE_ROLLBACK_CONFIGURATIONS` (2).

Nunca retira generaciones fijadas por:

- la configuración activa y las dos activas antes que ella;
- el destino de una solicitud de despliegue pendiente;
- la configuración de una prueba pendiente o en curso;
- releases abiertos, sesiones de optimización no terminales y sus
  experimentos;
- o construidas hace menos de 14 días.

Retirar borra sus documentos de OpenSearch (`delete_by_query` limitado a
instancia + generación) y conserva el registro como `retired`. Las
construcciones colgadas más de una hora pasan a `failed` y se borran sus
documentos parciales.

Ejecución manual (dry run por defecto):

```bash
make vector-store-generations-cleanup                       # todo, simulación
make vector-store-generations-cleanup DRY_RUN=0 INSTANCE=vector-store-v4 RETENTION_DAYS=0
```

`INSTANCE` limita la limpieza a una instancia; las protecciones se calculan
siempre de forma global.

## Migración

`make vector-store-generations-migrate` (dry run) / `DRY_RUN=0` (aplica).
Idempotente.

1. Cada instancia con el antiguo `promoted_version` obtiene una generación
   `ready` con ese número, `migrated: true`, el conteo real de documentos y
   fingerprint vacío: se cargó desde el manifiesto de la fecha de promoción,
   que puede diferir del actual, así que un build nuevo nunca la reutiliza por
   error. Luego se eliminan los atributos `promoted_*`.
2. Cada herramienta guardada que nombra una instancia sin generación queda
   fijada a esa generación. Las instancias sin generación se reportan en
   `segment_tools_unresolved` (salida 1); no se adivina un pin.

Local, 2026-10-27: respaldo completo previo
(`backups/vector-store-generations-before-migration/`), migración aplicada y
repetida sin escrituras nuevas. Se crearon `vector-store-v1@g1`,
`vector-store-v3@g1`, `vector-store-v4@g184` y `vector-store-v5@g184`; ninguna
herramienta local necesitaba pin. **OKD no se ha migrado.** Allí el orden
importa: con el código nuevo y los datos sin migrar no existe ningún registro
de generación, así que las búsquedas de producción devolverían vacío. Hacer
respaldo, desplegar API y worker, correr el dry run y aplicar la migración
antes de dejar pasar tráfico de alertas.

## Hashes históricos

- Configuraciones: el resolver omite `vector_store_generation: null`, así que
  las versiones sin pin conservan el hash con el que se fijaron. Una versión
  con pin numérico (nueva o migrada) tiene un contenido distinto: la evidencia
  H11/H12 tomada antes de migrar esa versión no se puede reutilizar y hay que
  volver a validarla.
- Vector Store: antes el pin era la versión de la instancia; ahora es el
  número de generación. Los pins de Vector Store anteriores ya no resuelven:
  validaciones y releases abiertos con esos pins deben repetirse.

## Benchmarks (local, 2026-10-27)

Resultados completos en `docs/benchmarks/`.

**Analizador en español** (`make vector-store-spanish-bench`). Treinta
consultas curadas sobre catorce textos reales de la Biblioteca, en seis
categorías, con embeddings reales. Se comparó el analizador `spanish` actual
contra `standard` + `asciifolding` + stop words + palabras protegidas +
`light_spanish`.

| Analizador | BM25 MRR@5 | Híbrido MRR@5 |
| --- | --- | --- |
| `spanish` (actual) | 0,967 | 1,000 |
| alternativa | 0,967 | 1,000 |

No hubo mejora medida: **se conserva el analizador actual**. El corpus es
pequeño; no es evidencia de calidad productiva.

**kNN filtrado** (`make vector-store-knn-bench`). OpenSearch 2.19.1, mapping
de producción (Faiss HNSW, coseno, 3.072 dimensiones, m 24, ef 128), vectores
sintéticos normalizados, 30 consultas, filtro instancia + generación dentro
del kNN y verdad exacta para el recall.

| Instancias × generaciones × docs | Docs totales | ANN p95 | Híbrido p95 | Híbrido p95 durante un build | Recall@5 | Store |
| --- | --- | --- | --- | --- | --- | --- |
| 5 × 1 × 200 | 1.000 | 4,5 ms | 7,9 ms | 27,6 ms | 1,0 | 0,08 GB |
| 5 × 5 × 200 | 5.000 | 4,4 ms | 7,7 ms | 23,0 ms | 1,0 | 0,38 GB |
| 5 × 20 × 200 | 20.000 | 19,4 ms | 15,4 ms | 33,2 ms | 1,0 | 1,85 GB |
| 5 × 50 × 200 | 50.000 | 14,6 ms | 22,0 ms | 55,8 ms | 1,0 | 5,61 GB |

**No medido**: 20 instancias y 1.000 documentos por generación. Tras el caso
de 50 generaciones, OpenSearch excedió el tiempo de eventos de cluster
mientras fusionaba segmentos; se recuperó sin reinicio y la corrida se
detuvo. Esas celdas no se extrapolan. Completarlas requiere un OpenSearch
aislado con recursos dedicados, fuera del stack compartido: 3.072 dimensiones
multiplican el store y las fusiones mucho más que el tamaño crudo de los
vectores. La métrica de memoria del grafo kNN dio 0; no significa consumo
cero, porque el filtrado Faiss puede resolver por búsqueda exacta.

Lectura práctica: el store crece linealmente con las generaciones retenidas
y la latencia filtrada se mantuvo en decenas de milisegundos con recall 1,0.
La retención de 14 días acota ese crecimiento; si una instancia acumula
decenas de generaciones activas, medir en el entorno real antes de ampliarla.

## Pruebas

- Unitarias: `make test-unit-vector-store` (build, idempotencia, fallos,
  pins, limpieza con propiedad Hypothesis y alcance por instancia);
  `tests/test_application/test_use_cases/test_configurations.py` (pin al
  guardar, activación directa rechazada, pin retirado);
  router, resolver, promotor H12 y `delete_generation` en
  `tests/test_infrastructure/`.
- Integración: `make test-integration-vector-store-generations` (repositorio
  y migración en un DynamoDB Local desechable).
- E2E real: `frontend_mockup/e2e/vector-store-generation-lifecycle-real.spec.ts`
  construye N, prueba y despliega una configuración que la fija, construye N+1
  sin cambiar producción, publica N+1 con aprobación, retira una generación
  sin protección, rechaza una prueba con pin retirado y revierte a N.
