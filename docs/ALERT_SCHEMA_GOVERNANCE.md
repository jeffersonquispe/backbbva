# Esquema de alerta — diseño, gobierno y tareas

Documento único del tema: estado actual, diseño, gobierno, UI/UX, campos
de la v1 y tareas. Evaluado y decidido con el usuario el 2026-10-09 sobre
`feature/version_0_0_3`.

**Alcance:** se rehace desde cero, **sin retrocompatibilidad** por ahora:
no hay `v0`, ni reconstrucción de alertas antiguas, ni upcasters. Lo que
hoy guarda la pestaña "Esquema" se descarta.

## 1. Qué hay hoy

| Pieza | Estado |
| --- | --- |
| Payload crudo de ARIC | Se guarda en `AlertRecord.payload` (DynamoDB). Lo leen directamente la cola y el Resumen de `/alerta/$id`, las métricas (`payload_dimensions`, `record_alert_metrics_event.py:61`) y el envío a dataset (`CurateAlertToDatasetUseCase`). |
| Normalización | `pre_process_alert.py`, con alias fijos en código (`_MANDATORY_FIELD_PATHS`, `_CARD_ONLY_FIELD_PATHS`, `_OPTIONAL_FIELD_PATHS`, `_PAYLOAD_ARIC_SIGNAL_PATHS`) para ARIC crudo y `Muestra_total_ARIA.csv`. Si falta un obligatorio, escala a analista. |
| Enriquecimiento | Señales de ARIC (`fetch_signals`) y, del host: perfil del cliente, historial transaccional y cambios de datos personales. |
| Alerta normalizada | Sólo existe como salida del paso `pre_process` del workflow: no está en la alerta ni tiene versión. |
| Salida del agente | DTOs por paso con partes libres (`model_output`, `research_delegations`, `vector_store_interactions`); el front la lee campo a campo. |
| Catálogo de presentación | No existe. Etiquetas duplicadas en el front (`FIELD_LABELS`, `MAX_AMOUNT_LABELS`, `DETAIL_FIELDS`), tres formas de leer la alerta y tres formatos de monto. |
| Pestaña "Esquema" | `SegmentParserSection`, sólo `manager`/`release_manager`. Se guarda copiada en cada segmento de la configuración y **el backend nunca la lee**. |
| Versión de configuración | La alerta de producción sólo guarda `configuration_id`; la versión sólo queda fijada en test runs. |
| Mapeo alerta ↔ dataset | `AlertFieldMapping` con `upsert` sin historial: no se sabe con qué regla se armó cada fila. |
| Solicitudes de despliegue | `/configuration-deploy-requests`: solicita `channel_manager`, aprueba `manager`/`release_manager`, con vista previa de cambios. No impide aprobar la propia solicitud; `requested_by` guarda el nombre, no el id. |
| Tramos de monto | La versión del juego de tramos es **obsoleta** y se retira. |

## 2. Principios

1. **La entrada no exige nada.** Todo payload de ARIC se acepta y se
   guarda crudo. Obligatoriedad, ubicaciones y tipos los define el
   esquema y se aplican en el pre-proceso; si falla, la alerta escala a
   analista con la lista de campos que faltaron.
2. **Se procesa una vez y no se modifica.** La alerta canónica se calcula
   con el esquema activo al llegar y queda sellada con su versión.
3. **Todas las vistas leen la canónica**: cola, detalle, histórico,
   métricas, Testing y datasets. El payload crudo sólo sirve para
   auditoría y para volver a procesar en Testing.
4. **Configuración y Testing no modifican la alerta.** Un cambio de
   esquema o de configuración afecta sólo a las alertas nuevas. Testing
   vuelve a procesar el payload crudo con una versión candidata y guarda
   el resultado en el test run.

## 3. La alerta canónica

```
{
  schema_version,
  configuration_ref: { configuration_id, version },
  raw_payload_ref,                      # almacenamiento de objetos
  input:   { ...campos is_alert, no is_label, origen aric/host },
  labels:  { ...campos is_label },
  history_prev_alerta: [ { ...campos is_history } ],
  agent_output: { ...campos de origen aria (resumen) },
  agent_output_ref                      # salida completa, almacenamiento de objetos
}
```

**Dónde se guarda:**
- **Almacenamiento de objetos:** payload crudo, salida del agente
  (razonamientos, investigación, SHAP; como
  `DocumentAnalystDecisionOutput.object_storage_ref`) y el registro de
  auditoría de consultas al "Evento original".
- **DynamoDB** (límite de 400 KB por ítem): `input`, `labels`,
  `history_prev_alerta`, versiones y referencias.

**`labels`** son los campos de desenlace (`is_label`). **Nunca entran al
agente**: en Testing sólo sirven para evaluar el run; en datasets van a
columnas de etiqueta separadas; en producción se llenan después
(revisión de fraude).

**Salida del agente:** se cataloga en el mismo esquema con `data_source:
aria`; `field_ds_loc` es la ruta dentro de la salida de cada paso (p. ej.
`classification.fraud_classification`, `detector.model_output.score`).
Los campos que el esquema declara se copian a `agent_output` en DynamoDB
para mostrarlos y filtrarlos; la salida completa queda en almacenamiento
de objetos. Las partes que hoy son diccionarios libres se tipan para que
sus rutas sean estables.

## 4. El esquema

Configuración de manager **con efecto inmediato**, sobre el modelo de
`OperationalSettings` ("Operación (inmediata)"): una versión aprobada se
aplica al instante a las alertas nuevas y cada versión queda en el
historial. Es una entidad propia, **fuera de la configuración del
agente**: si fuera dentro, un despliegue de `channel_manager` arrastraría
un cambio que afecta a todos los canales.

### 4.1 Modelo de datos

```
AlertSchemaVersion
  version            int, correlativo
  status             draft | proposed | active | historical | rejected
  fields             [AlertSchemaField]
  field_roles        { role: field_id }   (§4.2)
  proposed_by, proposed_at, approved_by, approved_at     (ids de usuario)
  impact_acknowledged  bool  (§5.6)
  based_on_version   int     (concurrencia optimista, como las configuraciones)

AlertSchemaField
  id, data_source, field, field_name, field_ds_loc, type,
  is_alert, is_mandatory, is_history, is_core, is_label,
  is_sensible, sensitivity_strategy, group, description,
  use_locale, locale_type
```

| Atributo | Valores | Para qué |
| --- | --- | --- |
| `id` | texto | Identificador del campo |
| `data_source` | `aric`, `host`, `aria` (ampliable) | Origen del dato. `aria` = generado por el agente |
| `field` | texto | Nombre canónico (`amount`, `customer_id`, …) |
| `field_name` | texto | Nombre visible ("Monto", "Cliente", …) |
| `field_ds_loc` | `campoA.campoB.campoC` | Ubicación en el objeto de origen. Si atraviesa una lista, toma el primer elemento |
| `type` | `string`, `number`, `bool`, `date`, `datetime`, `list` | Valida el valor y decide el formato |
| `is_alert` | bool | Forma parte de la alerta (`input` o `labels`) |
| `is_mandatory` | bool | Si falta, la alerta escala a analista |
| `is_history` | bool | Forma parte de `history_prev_alerta` |
| `is_core` | bool | Sólo sobre estos se construyen elementos fijos (columnas de la cola, monto destacado, filtros) |
| `is_label` | bool | Campo de desenlace: nunca entra al agente |
| `is_sensible` | bool | Dato sensible |
| `sensitivity_strategy` | `anonymize`, `obfuscate` | **Anonimizar**: seudónimo estable (no identifica, permite agrupar). **Ofuscar**: enmascarado al mostrar (`****5678`). Aplica en Sugerencias, "Evento original", exportaciones y simulador |
| `group` | texto | Agrupación en pantalla |
| `description` | texto | Qué significa el campo |
| `use_locale` | bool | Si el valor se formatea con convención regional |
| `locale_type` | p. ej. `es-CO` | Convención a usar si `use_locale` |

**Reglas de la entidad:**
- **Varias ubicaciones para un mismo dato** (hoy ARIC crudo y
  `Muestra_total_ARIA.csv`): una fila por ubicación con el mismo
  `field`; gana la primera presente según el orden de las filas.
- **Mismo `field` en alerta e historial** (p. ej. `amount`): filas
  distintas, una con `is_alert` y otra con `is_history`; en el historial
  `field_ds_loc` es relativo a cada registro del historial.
- Un campo que llega sin estar en el esquema se conserva y se muestra en
  "Otros" con su nombre técnico.

**Validaciones al guardar** (bloquean): `field_ds_loc` duplicado para el
mismo `data_source`; campo `is_core` sin `field_name`; `is_label` junto
con `is_history`; `is_sensible` sin `sensitivity_strategy`; `use_locale`
sin `locale_type`; rol obligatorio (§4.2) sin asignar, asignado a un
campo inexistente o de tipo incompatible; un campo de desenlace conocido
(`marcacion_final`, `tipo`, …) sin `is_label`; `is_mandatory` en un
campo de origen `aria` (lo genera el agente, no puede faltar a la
entrada).

### 4.2 Campos de sistema (roles)

Algunos datos los usa la plataforma en varios pasos, no sólo para
mostrarlos: entrypoint, tipo de evento, canal, monto… y sus
distribuciones alimentan la segmentación, el perfilado, las métricas y
el simulador. El código **no los busca por nombre**: pide un **rol**, y
el esquema dice, con un selector, qué campo cumple cada rol
(`field_roles`). Si mañana el tipo de evento llega en otro campo, se
cambia el selector, no el código.

La lista de roles la fija el código; el esquema sólo los asigna:

| Rol | Tipo | Obligatorio asignar | Lo usan hoy |
| --- | --- | --- | --- |
| `event_id` | string | ✓ | Consulta de señales de ARIC, trazabilidad |
| `event_time` | datetime | ✓ | Workflow, perfilado determinista, ventanas de historial |
| `event_type` | string | ✓ | Segmentación (`resolve_alert_segment`), perfilado determinista, métricas, catálogo de tags |
| `channel` | string | ✓ | Segmentación, perfilado determinista, métricas (dimensión canal), análisis de historial |
| `entrypoint` | string | ✓ | Segmentación, perfilado determinista, métricas (dimensión subcanal) |
| `amount` | number | ✓ (asignación) | Perfilado determinista, métricas (dimensión monto), análisis de historial |
| `customer_id` | string | ✓ | Consultas al host (perfil, historial, cambios de datos) |
| `account_id` | string | | Consulta del historial al host |
| `session_id` | string | | Consulta de señales de ARIC |

**Reglas:**
- Un rol se asigna a un único campo `is_alert` de tipo compatible. Los
  siete roles marcados ✓ requieren asignación en el esquema; eso no implica
  que todos sus valores deban venir en cada transacción. Si falta `amount`,
  la alerta continúa con el monto ausente, y consumidores como métricas y
  perfilado reciben ese valor como ausente. Los otros seis roles mantienen
  su obligatoriedad por transacción.
- **Distribuciones:** el análisis diario (§4.4) calcula, además de la
  presencia, la distribución de los campos asignados a roles (valores y
  frecuencias en categóricos; percentiles en numéricos). Es la misma
  distribución que siembra el simulador y la que comparan métricas y
  segmentación, así que todos los pasos ven el mismo dato.
- Cambiar un selector es un cambio de esquema: pasa por propuesta y
  aprobación (§5), genera corte en las gráficas y avisa del impacto en
  segmentos, reglas y modelos que dependan del rol.
- Añadir un rol nuevo requiere código (el consumidor que lo usa).

### 4.3 Usos del esquema

- **Pre-proceso:** recorre los campos del esquema activo, extrae cada
  valor de su `field_ds_loc` en el objeto de su `data_source`, valida
  `type` y `is_mandatory`, y arma `input`, `labels` e historial.
  Reemplaza todas las tablas `_*_PATHS` del código. Los campos `aria` se
  extraen al terminar cada paso del agente.
- **Consumidores por rol:** segmentación, perfilado determinista,
  análisis de historial, consultas al host y a ARIC leen los datos fijos
  vía `field_roles`, no por nombre de campo.
- **Métricas:** las dimensiones canal, subcanal y monto son los roles
  `channel`, `entrypoint` y `amount`. Cada snapshot de métricas guarda
  su `schema_version`. `/dashboard` y `/monitor` marcan en el tiempo cada
  activación de esquema o de configuración (corte con la versión).
- **Datasets:** "Al dataset" añade `input` + `labels` +
  `schema_version`, no el payload crudo mapeado. El mapeo sólo queda
  para exportar a formatos externos.
- **Simulador:** hereda los campos de origen `aric` del esquema activo;
  los parámetros de cada distribución se siembran desde un dataset
  elegido por el usuario (frecuencias en categóricas; normal /
  log-normal / Poisson en numéricas, generador de #20). Los campos se
  generan por separado: sirve para carga y validación del esquema, no
  para medir detección (eso sigue en los lotes CSV de Testing). Campos
  `is_sensible`: sintéticos. `is_label`: no se siembran.

### 4.4 Análisis diario de presencia y distribuciones

Un job diario en el `scheduler` (Celery Beat) recorre las alertas del día
y calcula por campo: en cuántas llegó, última vez visto y tendencia
frente a días anteriores; para los campos asignados a roles, también su
distribución. Lista además las ubicaciones que llegan sin estar en el
esquema, con su frecuencia. No hay umbral fijo: el resultado alimenta la
pestaña Sugerencias y las distribuciones de §4.2.

## 5. Gobierno

El esquema afecta a **todos los canales**, así que lo gobiernan sólo
`manager` y `release_manager`, con permiso nuevo **`alert_schema`** (no
se reutiliza `configuration`).

| Rol | Papel |
| --- | --- |
| `manager`, `release_manager` | Editan borradores, proponen y aprueban. **Nunca aprueban su propia propuesta** |
| `channel_manager` | Fuera, aunque tenga el resto de permisos |
| `data_analyst` | Lectura del catálogo (desde Biblioteca) |
| `fraud_analyst`, `ops_analyst` | Consumen; "Reportar campo" crea una sugerencia |

**Flujo:** `draft` → `proposed` → aprobada por un usuario distinto →
`active` al instante (la anterior pasa a `historical`); o `rejected`.
Volver atrás es proponer de nuevo una versión histórica, por el mismo
flujo.

**Reglas:**
1. El backend verifica que quien aprueba no es quien propuso, **por id**.
2. La propuesta muestra la comparación con la versión activa (campos
   añadidos, cambiados, quitados).
3. **No se exige test run** para aprobar.
4. **Detección automática:** el análisis diario (§4.4) convierte campos
   nuevos y caídas de presencia en sugerencias.
5. **Concurrencia:** si la versión activa cambió desde que se creó el
   borrador (`based_on_version`), la propuesta se rechaza y hay que
   rehacer el borrador sobre la nueva activa.
6. **Campos en uso:** quitar o cambiar un campo que usa una rúbrica, una
   regla determinista o un modelo XGBoost activo **no se bloquea, se
   avisa**: la propuesta lista qué configuraciones y modelos lo usan y
   quien aprueba debe confirmarlo (`impact_acknowledged`).
7. **Auditoría:** cada consulta al "Evento original (ARIC)" queda
   registrada (quién, cuándo, qué alerta) en almacenamiento de objetos.

Para propuestas y aprobación se reutiliza `/configuration-deploy-requests`
(ya tiene vista previa de cambios), corrigiendo lo de §1: permitir que
`manager`/`release_manager` soliciten para esquemas, guardar ids y
rechazar la auto-aprobación.

### 5.1 API

| Método y ruta | Rol | Qué hace |
| --- | --- | --- |
| `GET /alert-schema/active` | todos los autenticados | Esquema activo (lo usa el front para pintar) |
| `GET /alert-schema/versions`, `GET /alert-schema/versions/{v}` | `alert_schema`, `data_analyst` (lectura) | Historial y detalle |
| `POST /alert-schema/drafts` | `alert_schema` | Crea o actualiza un borrador (`based_on_version`) |
| `POST /alert-schema/versions/{v}/propose` | `alert_schema` | Propone; devuelve comparación e impacto |
| `POST /alert-schema/versions/{v}/approve` | `alert_schema`, distinto de quien propuso | Activa al instante (`impact_acknowledged` si hay impacto) |
| `POST /alert-schema/versions/{v}/reject` | `alert_schema` | Rechaza |
| `GET /alert-schema/presence` | `alert_schema` | Último análisis diario |
| `POST /alert-schema/suggestions` | `fraud_analyst`, `ops_analyst` | "Reportar campo" |
| `GET /alerts/{id}/raw` | `manager`, `release_manager` | Evento original (con `sensitivity_strategy` aplicada); registra la consulta |

## 6. UI/UX

**Configuración → Esquema** (`manager`, `release_manager`). Reemplaza la
pestaña actual, con selector de versión propio y cabecera con versión
activa, estado y quién propuso/aprobó (patrón de
`ConfigurationVersionGuide`). Sub-pestañas:
1. **Campos**: tablas por destino (Alerta / Resultado del agente / Desenlace / Historial),
   agrupadas por `group`, con filtros por `data_source`. Cada fila edita
   los atributos de §4.1; las ubicaciones alternativas de un mismo
   `field` se ven juntas en orden.
2. **Campos de sistema**: una fila por rol (§4.2) con un selector de
   los campos `is_alert` de tipo compatible, la distribución del último
   análisis diario del campo elegido y los pasos que lo usan. Aviso:
   afecta sólo a alertas nuevas y deja un corte en las gráficas.
3. **Propuestas**: pendientes con su comparación; "Aprobar" deshabilitado
   y explicado para quien propuso. Si un campo quitado o cambiado se usa
   en una rúbrica, regla o modelo activo, aviso en amarillo con la lista
   y casilla "Entiendo el impacto" obligatoria para aprobar.
4. **Sugerencias**: resultado del último análisis diario (campos nuevos
   con cuántas alertas y ejemplo de valor con `sensitivity_strategy`
   aplicada; campos cuya presencia cayó, con su tendencia) y reportes de
   analistas. Acciones: "Añadir al borrador", "Ignorar".

**Detalle de alerta (`/alerta/$id`)**: un solo componente dirigido por el
esquema (base: `AlertFullData`) en Resumen, Data alerta, Usuario e
Historial; el Razonamiento muestra los campos de origen `aria`. Núcleo
ausente → "—" con tooltip. Pestaña "Evento original (ARIC)" sólo para
`manager`/`release_manager`. Versión discreta en la cabecera ("Esquema
v3 · Config X v7"). Banner con los campos que faltaron si escaló por el
esquema. Botón "Reportar campo" para `fraud_analyst`/`ops_analyst`.

**Cola**: columnas a partir de los campos `is_core` y de los roles; sin versión
visible.

**Testing**: mismo componente; "Desenlace esperado" (`labels`) separado
de la entrada; comparación activo vs candidato por caso; versiones en la
cabecera del run y de cada caso.

**Biblioteca**: "Al dataset" sin mapeo, mostrando columnas que llenará y
versión; mapeo de exportación sólo `manager`/`release_manager`; catálogo
en sólo lectura para `data_analyst`.

**Formato:** montos y fechas según `use_locale`/`locale_type` de cada
campo; la v1 usa `es-CO` (`$ 5.400.000,00`, `09/10/2026`).

## 7. Campos de la v1

La v1 parte del mapeo completo del seed E2E sobre `Muestra_total_ARIA.csv`:
roles y campos opcionales según `scripts/e2e_api_seed.py`. Los siete roles
deben estar asignados en el esquema; `amount` es opcional por transacción,
mientras que los otros seis roles siguen siendo obligatorios por transacción.
`output_tags` se conserva fuera del input y se usa como label únicamente en
entrenamiento/evaluación de entrenamiento; no es un label operativo de la
alerta en producción. Las ubicaciones son las columnas del CSV de referencia
y no afirman que esos mismos nombres existan en cada payload crudo de ARIC.

## 8. Tareas

| # | Tarea |
| --- | --- |
| E1 | ✅ 2026-10-09 (sin commit). Guardar `configuration_id` + `version` en toda alerta procesada, no sólo en test runs. |
| E2 | ✅ 2026-10-09 (sin commit). Entidad `AlertSchemaVersion`/`AlertSchemaField` (§4.1), API (§5.1), permiso `alert_schema`, roles (§4.2); retirado `AgentConfig.parser`. |
| E3 | ✅ 2026-10-09 (sin commit). Flujo de esquema separado de deploy-requests; se guardan ids y se bloquea la auto-aprobación; la auditoría del Evento original queda para E5 junto al almacenamiento de objetos. |
| E4 | ✅ 2026-10-09 (sin commit). Pre-proceso dirigido por el esquema activo; separa `input`, `labels`, historial y roles, con validación y escalación por datos faltantes. Nota: la alerta canónica persistida queda para E5. |
| E17 | ✅ 2026-10-09 (sin commit). Consumidores fijos leen roles y los prompts reciben `input` e historial sin `labels`; métricas mantienen compatibilidad de lectura para alertas previas a E4. |
| E5 | ✅ 2026-10-09 (sin commit). Payload crudo y salida del agente quedan en almacenamiento de objetos y la alerta persiste la canónica; se conserva `payload` sólo en fixtures legacy no persistidos para mantener la suite actual. |
| E6 | ✅ 2026-10-09 (sin commit). Métricas desde `input` con los roles `channel`/`entrypoint`/`amount`, `schema_version` en el snapshot y retirada la metadata obsoleta de tiers; sin desviaciones. |
| E7 | ✅ 2026-10-09 (sin commit). Endpoint de eventos de versión y marcadores de activación; `/monitor` no tenía series temporales que marcar. |
| E8 | ✅ 2026-10-09 (sin commit). Datasets desde la canónica; mapeo sólo para exportar, versionado por esquema y con historial. |
| E9 | ✅ 2026-10-09 (sin commit). Testing evalúa desde `alert.labels` filtrado por campos `is_label`; los inputs de todos los agentes usan sólo la entrada canónica y las pruebas verifican que ningún valor de label llegue a sus prompts. |
| E10 | ✅ 2026-10-10 (sin commit). Historial canónico desde campos `is_history`, adapter local determinista y tabla de detalle dirigida por esquema; los clientes no incluidos en el fixture local siguen mostrando historial vacío. |
| E11 | ✅ 2026-10-10 (sin commit). Simulador desde campos ARIC del esquema activo, con siembra de frecuencias y generadores numéricos desde dataset; sensibles sintéticos y labels excluidos. |
| E12 | ✅ 2026-10-09 (sin commit). Componente único dirigido por esquema en detalle, cola, Testing e historial; formato por `locale_type`, faltantes, evento original restringido y sugerencias; el endpoint canónico de cola/detalle debe mantener la forma `input`/`labels`/`history_prev_alerta`/`agent_output`. |
| E13 | ✅ 2026-10-10 (sin commit). Front: Configuración → Esquema con las 4 sub-pestañas; la v1 sigue vacía y presencia/distribuciones quedan como placeholder hasta E16. |
| E14 | ✅ 2026-10-10 (sin commit). Testing permite fijar esquemas draft/proposed, conserva comparación activa/candidata de pre-proceso y separa etiquetas del input; no se añadió compatibilidad para registros antiguos sin esa metadata. |
| E15 | ✅ 2026-10-10 (sin commit). Biblioteca muestra el esquema activo en solo lectura para `data_analyst`, la curación lista entrada/etiquetas y versión sin mapeo, y el mapeo queda reservado a exportación para `manager`/`release_manager`; se restringió además la pestaña de esquema al permiso `alert_schema`. |
| E16 | ✅ 2026-10-10 (sin commit). Análisis diario, reporte DynamoDB, endpoint protegido y UI de presencia/distribuciones; los payloads crudos sólo se inspeccionan cuando están disponibles en fixtures, porque producción conserva únicamente su referencia de objetos. |

Orden: E1 → E2 → E3 → E4 → E17 → E5 → (E6, E7, E8, E9 en paralelo) → E12 →
E13 → E14 → E15 → E16. E10 y E11 cuando haya datos de historial y el
esquema esté estable.

## 9. Decisiones de alcance

- No hay obligatoriedad condicional. `card_bin` y `authorization_phase`
  se descartan como campos obligatorios sólo-tarjeta.
- `output_tags` es label únicamente para entrenamiento/evaluación de
  entrenamiento; se excluye del input de agentes.
- La asignación del rol `amount` es obligatoria en el esquema, pero su valor
  puede faltar por transacción sin bloquear el procesamiento.
- B1 (§8) cerró la definición del contenido v1. La carga y aprobación por el
  flujo de gobierno sigue pendiente en B2.

## 10. Estado del trabajo (actualizado 2026-10-13)

E1–E17 están commiteadas: backend en `b943cff` y frontend en `87e8bc4`
(`feature/version_0_0_3` en ambos repos). Durante la revisión ya se
corrigieron el 500 en `/analyst-queue` (el modelo de respuesta aún exigía
`payload`) y la tabla `alert_schema_suggestions`, que no se creaba al arrancar.

Respaldos: backup real verificado y tests en `e746e61`; de B3 queda probar
el restore contra el stack local y la decisión sobre los datos antiguos. La suite real de esquema C1–C6 está commiteada
(frontend `4b3a72a`, `462efe4`, `76eb6bd`; backend `3b31ae4`, `a3e82cf`) y
verificada contra la API local.

### Bloque A — Calidad (antes del commit)

| # | Tarea | Responsable | Depende de |
| --- | --- | --- | --- |
| A1 | ✅ 2026-10-11. Revisión focalizada de E2–E17: se corrigió `raw` para aplicar sensibilidad sólo a ARIC y atravesar listas tomando el primer elemento; se verificó el gobierno por ids y los límites de permiso. | Claude | — |
| A2 | ✅ 2026-10-11. Tests HTTP para `raw` (roles, 404, sensibilidad y auditoría) y `/alert-schema/*` (acceso al activo, historial y roles). | Claude | A1 |
| A3 | ✅ 2026-10-12. Aceptada la desviación de E3: las propuestas de esquema siguen su propio flujo, separado de `/configuration-deploy-requests` (ver `ALERT_SCHEMA_E2E_DELEGATION.md`). | Usuario | — |
| A4 | ✅ 2026-10-11. `index.html` del nginx local queda con `Cache-Control: no-cache`; el variant OKD ya lo tenía. | Claude | — |
| A5 | ✅ 2026-10-13. Commit completo: backend `b943cff`, `e2e-seed`/`e2e-presence` y `scripts/e2e_api_seed.py`/`e2e_api_wait_presence.py` en `1f0a7ad`; frontend `87e8bc4` (componentes `alert/`, `configuracion/schema/`, `SchemaComparison` y specs E2E). La cobertura ampliada de C1–C6 ya está implementada y verificada. | Usuario + Claude | A1, A2, A4 |

### Bloque B — Puesta en marcha local

| # | Tarea | Responsable | Depende de |
| --- | --- | --- | --- |
| B1 | ✅ 2026-10-13. Definido el contenido de la v1 desde el mapeo completo del seed: siete roles asignados; `amount` opcional por transacción y los otros seis obligatorios; labels de desenlace separados del input, con `output_tags` reservado para entrenamiento; campos restantes opcionales y sin campos CSV declarados como historial. | Usuario + equipo | — |
| B2 | **Siguiente.** Cargar la v1 por Configuración → Esquema: propone un `manager`/`release_manager`, aprueba otro distinto. | Usuario | B1 |
| B3 | ✅ 2026-10-14. Backend en `553c5cc`, `0207334` y `e746e61` (backup/restore confiables, `make db-restore` dentro del worker y tests en `tests/test_infrastructure/test_db_backup.py`); pantalla `/backups` en `e0bf774`. Restore real ejecutado contra el stack local desde `backups/20261014T040510Z`: 670 ítems DynamoDB y 377 objetos restaurados; el manifiesto no tiene snapshot de OpenSearch (`opensearch: null`). Se conservan los datos antiguos; no se ejecutó `db-prune`. | Claude | — |

### Bloque C — Verificación de punta a punta (con la v1 activa)

Los seis tests de `alert-schema-real-api.spec.ts` usan su propio esquema
sembrado por `make e2e-seed`, así que pueden correr antes de B2. La
verificación manual con la v1 real sí depende de B2. La corrida limpia
`make e2e-real E2E_FROM=0` pasó los seis tests y el análisis de presencia.
`E2E_FROM=1..6` permite reanudar sobre el estado existente; la reanudación desde
C5 también se verificó.

| # | Tarea | Responsable | Depende de |
| --- | --- | --- | --- |
| C1 | ✅ E2E real verifica gobierno, tabs, aprobación cross-user, raw enmascarado, permiso y auditoría al abrir "Evento original". | Claude | B2 |
| C2 | ✅ E2E real verifica cola/detalle, formato `es-CO`, `agent_output`, historial, raw y curación al dataset. | Claude | B2 |
| C3 | ✅ E2E real verifica métricas por roles y corte de versión visible en `/dashboard`. | Claude | C2 |
| C4 | ✅ E2E real procesa cinco filas y verifica labels fuera del input, además de comparar campos y roles entre versiones. | Claude | B2 |
| C5 | ✅ E2E real verifica el contenido de Sugerencias y Campos de sistema junto con el reporte de presencia. | Claude | C2 |
| C6 | ✅ E2E real verifica el seed del simulador sin labels, datos sensibles sintéticos, pesos categóricos y vista previa de 100 eventos. | Claude | B2 |

### Bloque D — Despliegue (OKD)

Desbloqueado por A5 y la verificación E2E verde de C1–C6.

| # | Tarea | Responsable | Depende de |
| --- | --- | --- | --- |
| D1 | Provisionar tablas `alert_schema_versions`, `alert_schema_presence_reports`, `alert_schema_suggestions` y `backups` (catálogo de respaldos, `553c5cc`). | Plataforma | A5 |
| D2 | Almacenamiento de objetos: payload crudo, salida del agente y auditoría del "Evento original" (bucket, permisos, retención). | Plataforma | A5 |
| D3 | `scheduler`: confirmar el job diario de presencia en OKD. | Plataforma | A5 |
| D4 | Cargar la v1 en OKD por el flujo de gobierno. | Usuario | B1, D1 |

Orden: Bloque A cerrado y B1 cerrado. B3 cerrado; después B2 → verificación manual de C1–C6 con
la v1 real → D1–D4.
