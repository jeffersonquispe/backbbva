# Pendientes legacy / MVC — terminar ARIA core agentes

Marcadores: `[ ]` pendiente · `[~]` en curso/parcial · `[x]` hecho y verificado por E2E real.
Leyenda: **[V]** verificar · **[I]** implementar · **[D]** diseño/decisión.
Archivo aparte de `PENDIENTES.md`. Anotado 2026-10-24.

## 1. Dashboard

- [x] **#1 [I] Barra lateral izquierda: parpadeo al cargar.** La barra tiene un perfilado de secciones por rol (`ROLE_NAV`), pero al inicio se renderiza **todo** y se alcanza a ver un parpadeo cuando recorta las opciones que el rol no puede ver. No debe ocurrir. ✅ Hecho 2026-10-24 (frontend 45de248): esqueleto hasta conocer el rol y estado persistido en `aria.sidebar.collapsed`; cubierto en `auth-real.spec.ts`.
  - Criterio: no renderizar el menú hasta conocer el rol del usuario autenticado (skeleton o nada), de modo que nunca se pinte una opción que luego desaparece.
  - Cubrir con E2E Playwright real (sin mocks), a través de nginx en `http://localhost`.
  - **Recordar el estado de la barra (colapsada/abierta):** persistir la última elección del usuario en `localStorage` (una clave, p. ej. `aria.sidebar.collapsed`) y usarla como valor inicial: si la colapsó, arranca colapsada; si la dejó abierta, abierta. Leer/escribir dentro de try/catch (puede fallar en ventana privada) con la barra abierta como valor por defecto. Leer el valor antes del primer render para no repetir el parpadeo de este mismo punto; considerar clave por usuario si el equipo comparte navegador. Incluirlo en el E2E (colapsar, recargar, verificar).
- [x] **#2 [I] Alertas iniciales del dashboard (rangos y falsos positivos): simplificar el texto.** Los avisos del inicio sobre rangos y falsos positivos tienen textos demasiado largos y contaminan visualmente. Reescribirlos cortos y fáciles de explicar al usuario (una frase; detalle bajo demanda, por ejemplo tooltip o "ver más"). ✅ Hecho 2026-10-24: avisos de una línea con "Ver más" (`MetricsNotices`); E2E en `observability-real.spec.ts`.
- [ ] **#3 [D][I] Filtros: reubicarlos o mejorarlos.** Repartir los filtros en otra sección (panel/drawer o barra propia) o rediseñarlos, para despejar la vista principal del dashboard.
- [x] **#4 [V] Botón "Rango personalizado".** Hoy no está probado de ninguna forma. Verificar el flujo completo (selección, validación de fechas, lectura de métricas vía `range_planner`) y agregar E2E. ✅ Verificado 2026-10-24 por E2E real (`reports-real.spec.ts`): selección, mismo día como rango válido, días futuros deshabilitados, lectura con el rango aplicado en Dashboard y Monitor, preset que lo reemplaza; API 422 en rango invertido/mal formado y vacío con ceros. Pendiente: inspección visual en Chrome (sesión expirada).
- [x] **#5 [V] Botón "Exportar reporte".** Tampoco está probado. Verificar que descarga el reporte correcto para el rango/filtros activos y agregar E2E. ✅ Verificado 2026-10-24 por E2E real (`reports-real.spec.ts`): el CSV lleva el rango personalizado y el filtro activo (Estado en Dashboard, Canal en Monitor). Pendiente: inspección visual en Chrome.

## Notas

- Todo cambio de frontend vive en `../frontend_mockup`; el E2E debe pasar contra el stack local reconstruido (`make e2e-all-local` o el escenario relevante).
- Si se toca el contrato de rutas/componentes, correr `make project-graph` (ver CLAUDE.md).

## 2. Alertas en proceso

- [ ] **#6 [D][I] Filtros mal ubicados y poco claros.** Siguen pegados al título; no se distingue qué es filtro, qué es título y qué es el botón/indicador de actualización. Separar visualmente en tres zonas: encabezado (título), barra de filtros propia debajo (o panel/drawer) y la acción de actualizar con su indicador de última actualización, claramente diferenciada.

## 3. Histórico de fraude

- [ ] **#7 [D][I] Filtros en la parte superior.** Mismo problema que #6; usar el mismo patrón de barra de filtros compartida.
- [ ] **#8 [V] Botones "Descargar plantilla" y "Cargar CSV".** No sabemos si funcionan. Verificar descarga de la plantilla, carga de un CSV válido, y manejo de CSV inválido (errores claros); agregar E2E real.

## 4. Monitor del agente

- [ ] **#9 [D][I] Filtros en la parte superior.** Mismo problema que #6 y #7.
- [x] **#10 [I] Exceso de alertas en muchos lugares.** Consolidar y reducir los avisos repartidos por la página (ver también #2). ✅ Hecho 2026-10-24: varios avisos se agrupan en uno ("N avisos sobre este rango") y el banner de agente degradado pasó a una línea.
- [x] **#11 [D][I] Página demasiado larga: convertir en tabs.** Los indicadores operativos y el resto se reparten en pestañas para no scrollear hasta el final: ✅ Hecho 2026-10-24: seis tabs (`MONITOR_TABS`), última pestaña recordada en `aria.monitor.tab`; test de componente y `observability-real.spec.ts` adaptados. "Porcentaje de recomendaciones" quedó como `% Recomendaciones`.
  - Indicadores generales
  - Indicadores de área
  - Analistas (nuestra perspectiva) y otros canales
  - Explicabilidad
  - Indicadores técnicos
  - Porcentaje de recomendaciones
- [x] **#12 [I] Deshabilitar VoiceBot y Vidi** por ahora (no se está llevando a cabo): ocultar o desactivar sus tabs/indicadores sin borrar el código. ✅ Hecho 2026-10-24: Voicebot y Bidi ocultos en el Monitor (`DISABLED_METHODS`), código intacto; verificado en `observability-real.spec.ts`.

## Transversal

- [ ] **#13 [D] Un solo componente de barra de filtros** reutilizado en dashboard (#3), alertas en proceso, histórico de fraude y monitor del agente, para que el patrón sea idéntico.

## 5. Componente de tabla (compartido)

- [x] **#14 [I] Redimensionar columnas arrastrando.** Arrastrar el borde derecho del encabezado para alargar/acortar la columna y ver nombres completos. Opcional: reordenar columnas arrastrando el encabezado (aparte del resize). Persistir anchos/orden por tabla en el navegador (`localStorage`, con try/catch). ✅ Hecho 2026-10-24: resize persistido por tabla (`aria.columnWidths.*`); reordenar columnas (opcional) no se hizo. E2E en `data-tables-real.spec.ts`.
- [x] **#15 [D][I] Botón "Columnas" más cerca de la tabla.** Hoy está encima de los botones de operaciones generales, lejos de la tabla. Moverlo a la barra de herramientas de la propia tabla, pegado a su borde superior y alineado a la derecha, junto a las otras acciones de tabla. ✅ Hecho 2026-10-24: botón en la barra de la tabla, pegado al borde superior y a la derecha. E2E en `data-tables-real.spec.ts`.
- [x] **#16 [I] Selector de límite por página (20 / 50 / 100)** en el pie de paginación, junto a los controles de página. Default 20. Verificar que el backend acepte y acote `limit` (tope máximo) y que la paginación por cursor se reinicie al cambiar el límite. Permite seleccionar/copiar más filas con el mouse. ✅ Hecho en frontend 2026-10-24 (20/50/100, default 20, vuelve a página 1). El tope de `limit`/cursor del backend no aplica: `DataTable` pagina en cliente.
- [ ] **E2E:** cubrir resize, columnas y cambio de límite en al menos una tabla real, vía nginx en `http://localhost`.

## 6. Formularios de creación/edición: un solo patrón (drawer lateral)

- [~] **#17 [D][I] Unificar en un único drawer lateral derecho superpuesto.** Hoy cada "nuevo/crear" se renderiza distinto: "Nueva prueba" abre un panel al lado derecho de la tabla, en Biblioteca sale un asistente y en Modelos un modal. Debe haber una sola alternativa: el mismo componente del Asistente ARIA (elemento `fixed`, barra lateral derecha superpuesta, con botón de cerrar), reutilizado.
  - **Avance (parcial, sin E2E ejecutado):** `ui/side-drawer.tsx` (`SideDrawer`: derecha, `fixed`, cerrar, Esc/clic fuera, foco atrapado, aviso `dirty`, marca `proposedByAria` para #18) aplicado a Nueva prueba, Nuevo modelo, datasets (crear vacío, subir, extraer, elegir registros, detalle, fila JSON), detalle de dataset de Testing, mapeo de campos (Biblioteca) y los tres catálogos de Configuración. **Pendiente:** Wizard/Studio/Resultados de entrenamiento (pantallas anchas), modales de watchlist/playbook y demás formularios inline de `biblioteca.tsx`/`configuracion.tsx`, `FraudReview`/`RoleModal` (decidir). E2E nuevo: `e2e/side-drawer-real.spec.ts`; ajustados `event-simulation-real` y `alert-schema-real-api`.
  - Crear un componente drawer compartido (extraer del Asistente ARIA) con encabezado, botón cerrar, cuerpo con scroll y pie de acciones.
  - Aplicarlo a: **Nueva prueba**, **Nueva flaca**, todos los formularios modales de **Biblioteca**, el modal de **Nuevo modelo** y todo lo de **Configuración** que hoy use modales u otro tipo de render.
  - Hacer un inventario previo (grep de modales/paneles en `../frontend_mockup`) para no dejar ninguno.
  - Definir comportamiento común: cerrar con Esc y clic fuera, foco atrapado, aviso si hay cambios sin guardar.
  - Actualizar E2E de cada flujo afectado (real, vía nginx en `http://localhost`) y correr `make project-graph` si cambian componentes.

## 7. Agente operador de formularios (crear/editar objetos)

- [ ] **#18 [D][I] El agente debe poder operar cada drawer/formulario de creación y edición.** No como intermediario que llena el formulario ni respondiendo "no puedo": debe **explorar los recursos que el formulario necesita** (enums, catálogos, listas de objetos ya creados) y **generar una propuesta del objeto a crear/editar**, que el usuario revisa y aprueba en el drawer (#17).
  - **Acciones por rol:** lista explícita de acciones que el agente puede ejecutar, filtrada server-side por el rol del usuario autenticado (mismo mecanismo que `ProjectGraph.hidden_for(role)` / `ROLE_PERMISSIONS`). El rol nunca viene del mensaje ni del modelo.
  - **Contexto por acción:** cada acción declara qué necesita (esquema de campos, enums, recursos relacionados) y el agente lo obtiene con herramientas de solo lectura (listar/buscar catálogos, instancias, datasets, modelos, etc.), igual que `search_project` / `describe_node`.
  - **Propuesta, no escritura directa:** el agente produce un borrador validado contra el esquema; el usuario confirma. Ya existen routers `agent_*_draft` (flag, modus operandi, similar case, taxonomy, watchlist): partir de ese patrón y generalizarlo en lugar de inventar otro (grep antes de crear).
  - **Contrato frontend:** que el drawer acepte un borrador precargado del agente (campos prellenados + marca de "propuesto por ARIA").
  - E2E real por acción integrada.

### Puntos de integración (formularios de creación/edición)

Inventario preliminar a partir de `../frontend_mockup/src/components` y los routers de la API; confirmar al implementar.

**Testing** (`testing/`)
- Nueva prueba — `NewTestRunModal`, `DatasetTestForm`, `FormularioTestForm` (`test_runs_router`, `scenarios_router`)
- Detalle/edición de dataset de prueba — `DatasetDetailModal`

**Biblioteca** (`biblioteca/`)
- Watchlists y sus elementos — `WatchlistManager`, `WatchlistElementsModal` (`watchlists_router`, ya hay `agent_watchlist_draft`)
- Modus operandi / playbook — `ModusOperandiPlaybookModal` (`modus_operandi_library_router`, ya hay `agent_modus_operandi_draft`)
- Flags — (`flag_library_router`, ya hay `agent_flag_draft`)
- Casos similares — (`similar_case_library_router`, ya hay `agent_similar_case_draft`)
- Taxonomías — (`taxonomy_library_router`, ya hay `agent_taxonomy_draft`)
- Canales — (`channel_library_router`)
- Bibliotecas de datasets — `DatasetLibraryManager`
- Mapeo de campos de alerta — `AlertFieldMappingEditor` (`alert_schema_router`)
- Instancias de Vector Store — (`vector_store_instances_router`)

**Datasets** (`datasets/`)
- Crear dataset vacío — `CreateEmptyDatasetModal`
- Subir dataset — `UploadDatasetModal`
- Extraer dataset — `ExtractDatasetModal`
- Seleccionar registros — `PickDatasetRecordsModal`
- Detalle/edición — `DatasetDetailDrawer`, `RowJsonModal`

**Modelos** (`modelos/`)
- Nuevo modelo — `ModelFormModal` (`models_router`)
- Entrenamiento — `ModelTrainingWizard`, `ModelDesignStudio`

**Configuración** (`configuracion/`)
- Catálogo de marcaciones — `MarcacionCatalogManager` (`marcacion_catalog_router`)
- Catálogo de métodos de resolución — `ResolutionMethodCatalogManager` (`resolution_method_catalog_router`)
- Catálogo de variables — `VariableCatalogManager` (`variable_catalog_router`)
- Segmentos — `SegmentoTab`
- Configuraciones del agente (rúbricas, detector, etc.) y solicitudes de despliegue — (`configurations_router`, `configuration_deploy_requests_router`)
- Catálogo de etiquetas — (`tag_catalog_router`)
- Objetivos del agente — (`agent_objectives_router`)
- Ajustes operativos / capacidad de analistas / optimizador — (`operational_settings_router`, `analyst_capacity_router`, `assistant_optimizer_settings_router`)

**Otros**
- Roles/permisos — `RoleModal` (sólo administración; evaluar si el agente debe poder operarlo)
- Revisión de fraude — `fraude/FraudReview` (marcación; decisión sensible, definir si el agente sólo propone)
- Histórico de fraude — carga de CSV (#8)
- Backups — (`backups_router`; probablemente fuera de alcance del agente)

**Fuera de alcance por defecto** (confirmar): diálogos de confirmación/borrado (`confirm-delete-dialog`, `LogoutDialog`), acciones destructivas.

## 8. Visualización tipo GitGraph de ramas de configuración

- [~] **#19 [D][I] Grafo de evolución de versiones/ramas de configuraciones** (estilo GitGraph): ver cómo han evolucionado las ramas, qué cambios se promovieron a producción y cómo se propagaron a las ramas posteriores hasta la actual.
  - **Avance (sin E2E ejecutado):** cada versión nueva guarda `parent_ref`; `GET /configurations/graph` expone el historial en solo lectura y Configuración lo presenta como nodos seleccionables. Se añadieron cobertura de API/UI real; falta ejecutar E2E por instrucción de la sesión.
  - **Estado actual del modelo:** `ConfigurationRecord` tiene `configuration_id` (linaje) + `version` (incrementa por edición), `active`, `ever_activated`, `activated_at`, `created_at`, `created_by`. **No hay puntero a padre ni a rama**: el historial es lineal por linaje y no se sabe de qué versión/configuración se derivó otra.
  - **[D] Decidir qué es una "rama":** cada linaje (`configuration_id`) es una rama y se bifurca al duplicar una configuración. Las candidatas paralelas parten de un mismo baseline mediante `parent_ref`; no se define semántica de merge.
  - **[I] Backend:** guardar `parent_ref` (`ConfigurationRef`: `configuration_id` + `version`) al crear una versión nueva o al duplicar; para las existentes, dejar `None` (inicio del grafo) o inferir el padre lineal (`version - 1`). Registrar eventos de promoción (activación a producción) con fecha y autor (hoy sólo hay `activated_at`/`ever_activated`, que se sobrescribe, no un historial). Endpoint de solo lectura que devuelva nodos y aristas (sin `Scan`; indexar por linaje). Permitir que la ejecución de investigación refiera versiones candidatas y su baseline mediante referencias explícitas a experimento/hipótesis; esas referencias sirven para navegar y visualizar, no crean pertenencia entre la configuración y el esquema ni cambian la semántica del linaje.
  - **[I] Frontend:** render del grafo con SVG propio o una librería ligera (p. ej. `@gitgraph/react`); nodo = versión, color = estado (activa, promovida alguna vez, borrador/probada), marcador de promoción a producción, clic abre el detalle. Mostrar referencias disponibles a hipótesis/experimento y decisión de promoción. Ubicarlo en Configuración (junto a `ConfigurationVersionGuide`).
  - **Límite:** "propagación de cambios" como en Git (merge) no existe; se mostraría **linaje**, no diffs fusionados. Si se quiere ver qué cambió entre nodos, es un diff de configuraciones aparte.
  - E2E real sobre el grafo.

## 9. Diagramas de workflow dentro de la plataforma

- [ ] **#20 [D][I] Llevar a la plataforma los diagramas de `docs/presentacion/aria_capacidades.html`** (roles por persona, etapas del pipeline, flujo). Ese HTML ya tiene ~68 SVG; reutilizarlos como componentes React compartidos (`WorkflowDiagram` y variantes), no redibujar. Cada diagrama debe ser **vivo cuando haya datos** (resaltar la etapa en curso, conteos por etapa) y **estático explicativo** en los demás casos. Colapsables, para no volver a alargar las páginas (ver #11).

  Propuesta de puntos de inserción (confirmar con el diseño):

  | Dónde | Diagrama | Qué muestra |
  |---|---|---|
  | **Detalle de alerta** (`alerta.$id`) | Pipeline de diez etapas, con la etapa actual y el resultado de cada paso (XGBoost, agente, adversarial, resolución, cola) | Dónde va esta alerta y por qué llegó aquí |
  | **Cola** (`cola`) | Embudo "evento → cola → persona decide", con quién interviene | Por qué una alerta llegó a un analista y qué sigue |
  | **Dashboard** (`dashboard`) | Mini-flujo del ciclo "del evento al aprendizaje" con conteos por etapa | Lectura rápida del sistema; sustituye textos largos (ver #2) |
  | **Monitor** (`monitor`) | Pipeline con salud/latencia/fallos por etapa, dentro del tab Indicadores técnicos (#11) | Dónde falla el flujo |
  | **Configuración** (`configuracion`) | Mapa de qué ajusta cada sección del pipeline (rúbricas, detector, adversarial, analista, documentación, segmentos) + grafo de versiones (#19) | Qué parte del flujo cambia cada ajuste |
  | **Configuración → despliegue** | Flujo "versionada y desplegada con aprobación" (quién propone, quién aprueba, activa) | Separación de funciones |
  | **Biblioteca** (`biblioteca`) | Cómo cada recurso (flags, modus operandi, casos, taxonomías, watchlists, Vector Store) alimenta al agente y en qué paso | Para qué sirve cada elemento |
  | **Modelos** (`modelos`) | XGBoost: entrenamiento → evaluación → promoción → puntúa primero en el Detector | Ciclo de vida del modelo |
  | **Histórico de fraude** (`historico-fraude`) | Cómo el `fraud_label` corrige el `mark` y alimenta métricas/aprendizaje | Por qué cargar el CSV importa |
  | **Testing** (`testing`, `testing.$runId`) | Misma muestra, versiones fijas → comparación; escenarios y test runs | Cómo se prueba una versión |
  | **Asistente / Optimizador / Orquestador** | Sesión → hallazgos → hipótesis → experimentos paralelos o secuenciales → evidencia/conclusión → decisión de promoción; incluir fuentes, particiones, presupuesto y bloqueos | Qué investigó el agente, cómo evaluó cada candidata y cuándo necesita intervención humana |
  | **Roles** (`RoleModal`, Configuración) | Matriz "seis roles, seis responsabilidades" y quién interviene en cada capacidad | Qué puede hacer cada rol |
  | **Onboarding** (`login` / primera visita) | Plano de seis capacidades, un mismo ciclo | Orientación general |
  | **Backups** (`backups`) | Flujo de respaldo y retención | Continuidad |

  - Dos niveles de reutilización: (1) diagramas estáticos extraídos de la presentación; (2) los de datos vivos (alerta, cola, monitor, dashboard) leen la API existente, sin endpoints nuevos salvo que falten conteos por etapa.
  - Agregarlos al grafo del proyecto (`scripts/project_graph_curated.json`) para que el chat del agente pueda citar el diagrama relevante.
  - Respetar tema claro/oscuro y ancho móvil; accesibles (texto alternativo o lista equivalente).
  - E2E real por página afectada.

## 10. Event API y enriquecimiento en el preproceso

- [ ] **#21 [D][I] Event API (componente nuevo, hoy no existe).** Servicio que escucha siempre y recibe los eventos de alertas.
  - **Esquema abierto:** sin restricciones de esquema en la entrada; la validación se hace en el preproceso y varía según el esquema de entrada activo (`AlertSchemaVersion`). El Event API no valida contenido (sólo lo mínimo para aceptar: JSON bien formado, tamaño máximo, autenticación del emisor).
  - **Sólo hace push** del evento a la **cola de producción**. Nada de testing, ni rutas de prueba, ni lógica de negocio. Los tests/simulaciones siguen su propio camino (simulador) y nunca pasan por aquí.
  - **[D resuelta parcialmente]:** contrato mínimo `{alert_id, event_id}`; `event_id` identifica el evento para deduplicar reintentos del emisor. Sigue pendiente decidir respuesta de aceptación (propuesta: 202 + id de recepción), comportamiento si la cola rechaza el push (error al emisor, sin perder el evento) y mecanismo concreto de idempotencia.
  - **[D] Despliegue:** proyecto/servicio propio y mínimo (como el simulador y el MCP: dependencias separadas, Dockerfile local + OKD en paridad, ver CLAUDE.md), sin importar FastAPI de la API principal ni infraestructura de persistencia. Hexagonal: puerto de publicación de eventos con adaptador de cola.
  - E2E real: enviar un evento al Event API y verificar que aparece en la cola productiva y arranca el flujo; verificar que ningún evento de test llega a esa cola.

- [ ] **#22 [D][I] Preproceso: de alerta resumida a alerta enriquecida.** En producción no llegará la alerta completa sino la **alerta resumida (básicamente un id)**. El preproceso debe: (1) hacer fetch de la información de la alerta, (2) hacer fetch de **otras fuentes** para complementarla, (3) validar contra el esquema activo y (4) pasar a las etapas siguientes.
  - **Sólo producción:** el enriquecimiento ocurre únicamente en el flujo de producción, cuando una alerta llega a ARIA desde el Event API. Ahí la alerta trae sólo la información base (básicamente el id), y los llamados a los servicios externos son lo que la completa; sin ellos no hay datos suficientes para las etapas siguientes. En testing/simulación/datasets la alerta ya viene completa: **no se llaman esas fuentes** (el preproceso se salta el enriquecimiento o usa adaptadores que no salen a servicios reales). Hacer explícito ese modo (p. ej. un origen `production` vs. `test` en el evento/ejecución) en vez de depender de qué campos vengan.
  - **Estado actual:** `application/use_cases/alerts/pre_process_alert.py` ya recibe puertos de fuentes (perfil de cliente, cambios de datos personales, historial de transacciones, ARIC) y reintenta (`MAX_FETCH_ATTEMPTS = 3`), pero en la práctica hoy sólo se carga el objeto y se valida. Hay que modelar el fetch real de la alerta por id y de fuentes adicionales.
  - **Modelarlo en el preproceso (la lambda/tarea de preproceso), no en la API de alertas** (decisión explícita). Las fuentes son conectores intercambiables (un puerto por fuente, adaptador por tecnología), configurables, agregables sin tocar casos de uso.
  - **[D resuelta parcialmente]:** contrato resumido `{alert_id, event_id}`. Ante fallos, reintentar de forma acotada; si falla una fuente necesaria para campos obligatorios del esquema activo, fallar el preproceso; si falla una fuente opcional, continuar y marcar el enriquecimiento como incompleto. Sigue pendiente definir orden/paralelismo, timeouts y clasificar qué fuentes alimentan campos obligatorios u opcionales.
  - **Integración pendiente:** el repo sólo tiene adaptadores mock de ARIC/Host y no define el servicio o almacenamiento donde resolver `alert_id` para obtener la alerta base. Acordar ese origen y los contratos de las fuentes antes de conectar adaptadores reales.
  - **[V] Verificar:** cómo se ve en el workflow y el monitor (estado y latencia del paso de preproceso por fuente) y que las rutas de datos (`schema_version_at_creation`) queden registradas.
  - Actualizar el diagrama del pipeline (#20) para mostrar Event API → cola de producción → preproceso (enriquecimiento) → etapas siguientes.

- [ ] **#23 [D][I] Preparación reproducible de datasets para diagnóstico y experimentos.** Al iniciar una investigación, crear un snapshot inmutable de staging y derivar de él las particiones de entrenamiento, validación y prueba final. Si se parte de un dataset cargado o del catálogo, preparar las mismas particiones; si la fuente es producción, obtener primero la muestra madura mediante el sampler existente y aplicar después la partición. No leer directamente índices de creación para saltarse la ventana de madurez, que debe ser configurable.
  - Guiar al usuario para definir y revisar los parámetros de separación: categoría/estratos, distribución objetivo, proporciones, semilla y columnas relevantes. Mostrar conteos y distribución resultante antes de confirmar; guardar parámetros, semilla, mapeos y referencia al snapshot para reproducir el split.
  - Mantener entrenamiento/validación para diagnóstico e iteración y reservar la partición final para la evaluación final, evitando que el diagnóstico la consuma. Comparar baseline y candidata sobre la misma muestra y partición.
  - Registrar el esquema usado como contexto de validación/evaluación, no como relación de pertenencia con la configuración. Ante incompatibilidad con otro esquema, emitir alertas explicativas.
  - El worker autorizado procesa filas y devuelve agregados con soporte mínimo; no exponer filas al LLM, chat ni insights. Incorporar límites de costo y volumen.
  - Coordinar el contrato y la experiencia de configuración del split con el backlog de datasets; cubrir fuentes cargada, catálogo y producción madura con E2E real.

- [ ] **#24 [D][I] Actualizar observabilidad para el ciclo científico del optimizador.** La observabilidad actual corresponde a una versión anterior del agente y no representa el andamiaje de sesiones, hallazgos, hipótesis, experimentos, verificaciones y decisiones que estamos incorporando.
  - Inventariar eventos y paneles actuales y definir instrumentación para el ciclo completo: etapa/estado, duración, espera en cola, reintentos, bloqueos y resultados inconclusos; mostrar concurrencia de experimentos y workers, presupuesto agregado, fuente y particiones del dataset, versión de esquema validada y límites/uso de embeddings.
  - Correlacionar sesión, hallazgo, hipótesis, experimento, ejecución y promoción en trazas, logs y auditoría mediante referencias opacas. No usar esos IDs como dimensiones de métricas: mantener atributos métricos de baja cardinalidad y respetar los límites de privacidad (sin filas, PII ni prompts).
  - Mostrar la trazabilidad de evidencia y decisiones desde el monitor y los diagramas vivos (#20), incluyendo cuándo el agente continúa autónomamente y cuándo queda bloqueado esperando aclaración humana.
  - Mantener OTLP como contrato de telemetría, auditoría de negocio mediante `AuditPort` y métricas de negocio agregadas según el contrato existente; no duplicar rollups como telemetría.
  - Cubrir el ciclo de vida y las restricciones de cardinalidad/privacidad con E2E real a través de nginx.
