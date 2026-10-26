# Pendientes legacy / MVC — terminar ARIA core agentes

Marcadores: `[ ]` pendiente · `[~]` en curso/parcial · `[x]` implementación completada. El estado de E2E se indica dentro de cada punto.
Leyenda: **[V]** verificar · **[I]** implementar · **[D]** diseño/decisión.
Archivo aparte de `PENDIENTES.md`. Anotado 2026-10-24.

## 1. Dashboard

- [x] **#1 [I] Barra lateral izquierda: parpadeo al cargar.** La barra tiene un perfilado de secciones por rol (`ROLE_NAV`), pero al inicio se renderiza **todo** y se alcanza a ver un parpadeo cuando recorta las opciones que el rol no puede ver. No debe ocurrir. ✅ Hecho 2026-10-24 (frontend 45de248): esqueleto hasta conocer el rol y estado persistido en `aria.sidebar.collapsed`; cubierto en `auth-real.spec.ts`.
  - Criterio: no renderizar el menú hasta conocer el rol del usuario autenticado (skeleton o nada), de modo que nunca se pinte una opción que luego desaparece.
  - Cubrir con E2E Playwright real (sin mocks), a través de nginx en `http://localhost`.
  - **Recordar el estado de la barra (colapsada/abierta):** persistir la última elección del usuario en `localStorage` (una clave, p. ej. `aria.sidebar.collapsed`) y usarla como valor inicial: si la colapsó, arranca colapsada; si la dejó abierta, abierta. Leer/escribir dentro de try/catch (puede fallar en ventana privada) con la barra abierta como valor por defecto. Leer el valor antes del primer render para no repetir el parpadeo de este mismo punto; considerar clave por usuario si el equipo comparte navegador. Incluirlo en el E2E (colapsar, recargar, verificar).
- [x] **#2 [I] Alertas iniciales del dashboard (rangos y falsos positivos): simplificar el texto.** Los avisos del inicio sobre rangos y falsos positivos tienen textos demasiado largos y contaminan visualmente. Reescribirlos cortos y fáciles de explicar al usuario (una frase; detalle bajo demanda, por ejemplo tooltip o "ver más"). ✅ Hecho 2026-10-24: avisos de una línea con "Ver más" (`MetricsNotices`); E2E en `observability-real.spec.ts`.
- [x] **#3 [D][I] Filtros: reubicarlos o mejorarlos.** Repartir los filtros en otra sección (panel/drawer o barra propia) o rediseñarlos, para despejar la vista principal del dashboard. ✅ Hecho (ver #13): filtros del Dashboard en su propia tira bajo el título.
- [x] **#4 [V] Botón "Rango personalizado".** Hoy no está probado de ninguna forma. Verificar el flujo completo (selección, validación de fechas, lectura de métricas vía `range_planner`) y agregar E2E. ✅ Verificado 2026-10-24 por E2E real (`reports-real.spec.ts`): selección, mismo día como rango válido, días futuros deshabilitados, lectura con el rango aplicado en Dashboard y Monitor, preset que lo reemplaza; API 422 en rango invertido/mal formado y vacío con ceros. Inspección visual en Chrome 2026-10-25: calendario con días futuros deshabilitados, "Aplicar" inactivo hasta elegir rango, chip "20 oct – 22 oct", estado de carga y métricas actualizadas.
- [x] **#5 [V] Botón "Exportar reporte".** Tampoco está probado. Verificar que descarga el reporte correcto para el rango/filtros activos y agregar E2E. ✅ Verificado 2026-10-24 por E2E real (`reports-real.spec.ts`): el CSV lleva el rango personalizado y el filtro activo (Estado en Dashboard, Canal en Monitor). Inspección visual en Chrome 2026-10-25: el botón descarga `reporte-dashboard-*.csv` con el rango activo y las cifras del Dashboard (164 alertas, 0/11 falsos positivos, SLA 100 %).

## Notas

- Todo cambio de frontend vive en `../frontend_mockup`; el E2E debe pasar contra el stack local reconstruido (`make e2e-all-local` o el escenario relevante).
- Si se toca el contrato de rutas/componentes, correr `make project-graph` (ver CLAUDE.md).

## 2. Alertas en proceso

- [x] **#6 [D][I] Filtros mal ubicados y poco claros.** Siguen pegados al título; no se distingue qué es filtro, qué es título y qué es el botón/indicador de actualización. Separar visualmente en tres zonas: encabezado (título), barra de filtros propia debajo (o panel/drawer) y la acción de actualizar con su indicador de última actualización, claramente diferenciada. ✅ Hecho (ver #13): título / tira de filtros / "Actualizar" con "Última actualización" aparte.

## 3. Histórico de fraude

- [x] **#7 [D][I] Filtros en la parte superior.** Mismo problema que #6; usar el mismo patrón de barra de filtros compartida. ✅ Hecho (ver #13): mismo patrón; plantilla y carga CSV en el encabezado.
- [x] **#8 [V] Botones "Descargar plantilla" y "Cargar CSV".** No sabemos si funcionan. Verificar descarga de la plantilla, carga de un CSV válido, y manejo de CSV inválido (errores claros); agregar E2E real. ✅ Verificado 2026-10-24 por E2E real (`fraud-review-real.spec.ts`): plantilla (nombre y cabecera), carga mixta con reporte por fila, `;`/BOM/mayúsculas, archivos rechazados (sin columna, vacío, no UTF-8), solo encabezado y reenvío. Sin bugs de producto. Inspección visual 2026-10-25: botones en el encabezado y "Cargar CSV" abre el selector de archivos; la plantilla se descargó en Chrome (`alert_id,fraud_label,note` + fila de ejemplo).

## 4. Monitor del agente

- [x] **#9 [D][I] Filtros en la parte superior.** Mismo problema que #6 y #7. ✅ Hecho (ver #13): mismo patrón en el Monitor.
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

- [x] **#13 [D] Un solo componente de barra de filtros** reutilizado en dashboard (#3), alertas en proceso, histórico de fraude y monitor del agente, para que el patrón sea idéntico. ✅ Hecho 2026-10-24: `PageHeader` + `FilterBar` (`components/PageHeader.tsx`) en Dashboard, En proceso, Histórico y Monitor; tres zonas separadas, contador de filtros activos y "Limpiar filtros", rango a la derecha de la tira. E2E en `data-tables-real.spec.ts`.

## 5. Componente de tabla (compartido)

- [x] **#14 [I] Redimensionar columnas arrastrando.** Arrastrar el borde derecho del encabezado para alargar/acortar la columna y ver nombres completos. Opcional: reordenar columnas arrastrando el encabezado (aparte del resize). Persistir anchos/orden por tabla en el navegador (`localStorage`, con try/catch). ✅ Hecho 2026-10-24: resize persistido por tabla (`aria.columnWidths.*`); reordenar columnas arrastrando el asa del encabezado, persistido por tabla (`aria.columnOrder.*`), hecho 2026-10-25 y verificado en Chrome (orden sobrevive a la recarga). E2E en `data-tables-real.spec.ts` (resize, orden, columnas, filas por página).
- [x] **#15 [D][I] Botón "Columnas" más cerca de la tabla.** Hoy está encima de los botones de operaciones generales, lejos de la tabla. Moverlo a la barra de herramientas de la propia tabla, pegado a su borde superior y alineado a la derecha, junto a las otras acciones de tabla. ✅ Hecho 2026-10-24: botón en la barra de la tabla, pegado al borde superior y a la derecha. E2E en `data-tables-real.spec.ts`.
- [x] **#16 [I] Selector de límite por página (20 / 50 / 100)** en el pie de paginación, junto a los controles de página. Default 20. Verificar que el backend acepte y acote `limit` (tope máximo) y que la paginación por cursor se reinicie al cambiar el límite. Permite seleccionar/copiar más filas con el mouse. ✅ Hecho en frontend 2026-10-24 (20/50/100, default 20, vuelve a página 1). El tope de `limit`/cursor del backend no aplica: `DataTable` pagina en cliente.
- [x] **E2E:** cubrir resize, columnas y cambio de límite en al menos una tabla real, vía nginx en `http://localhost`. ✅ Hecho 2026-10-25: `data-tables-real.spec.ts` (resize persistente, columnas, filas por página).

## 6. Formularios de creación/edición: un solo patrón (drawer lateral)

- [x] **#17 [D][I] Unificar en un único drawer lateral derecho superpuesto.** Los formularios de alta y edición usan el `SideDrawer` común: panel fijo a la derecha, cierre, foco atrapado y aviso de cambios sin guardar.
  - **Avance 2026-10-25:** `ui/side-drawer.tsx` ya se usa en Nueva prueba, Nuevo modelo/entrenamiento, datasets (crear vacío, subir, extraer, elegir registros, detalle y fila JSON), detalle de dataset de Testing, mapeo de campos y los tres catálogos de Configuración. Se migraron también alta/edición de listas negras/blancas, gestión de sus elementos y edición de playbook. La spec `e2e/side-drawer-real.spec.ts` se amplió para crear y editar una lista con API real.
  - **Inventario actualizado 2026-10-25:** los formularios de canal, taxonomía, modus operandi, flags, casos similares, playbook, watchlists, sus elementos y los catálogos de punto de integración, regla disparada y tipo de evento en Biblioteca usan `SideDrawer`; las operaciones de dataset de Biblioteca también usan el drawer compartido. El formulario de nueva configuración en `configuracion.tsx` sigue pendiente.
  - **Decisiones de alcance:** `RoleModal` ya no presenta formulario (devuelve `null`, los roles vienen del JWT/API); `FraudReview` es una acción de revisión/auditoría, no un formulario CRUD. `ModelDesignStudio` no tiene consumidores en el frontend y `ModelTrainingResults` es una vista de consulta; ambos quedan fuera de la migración CRUD. Los diálogos de confirmación y solicitudes/despliegues son acciones operativas, no formularios de alta/edición.
  - **E2E:** `side-drawer-real.spec.ts` cubre apertura de los formularios de Biblioteca con datos reales, alta/edición de watchlist, alta de valores en los tres catálogos de eventos y aviso de cambios sin guardar. Sigue pendiente correr los E2E focalizados y `make e2e-all-local` a través de nginx en `http://localhost:80`; todavía no se ejecutó ninguna corrida de esta tanda.
  - **Pendiente de implementación:** migrar el formulario de nueva configuración en `configuracion.tsx` al drawer compartido.
  - **Verificación pendiente:** ejecutar E2E focalizados para los flujos de Biblioteca y después `make e2e-all-local` por nginx en `http://localhost:80`.

## 7. Agente operador de formularios (crear/editar objetos)

- [x] **#18 [D][I] El agente opera formularios mediante propuestas que se revisan y aprueban en el drawer (#17).** Alcance implementado en esta iteración: taxonomía, modus operandi/playbook, flag, caso similar y metadatos de watchlist; no opera sus elementos.
  - **Decisión de permisos aplicada:** `GET /agent/draft-actions` devuelve acciones solo si el usuario autenticado tiene `configuration` y `library`. Actualmente eso habilita a `manager` y `channel_manager`. El catálogo visible y los cinco endpoints de borrador comparten este filtro; `release_manager`, `data_analyst`, `fraud_analyst` y `ops_analyst` no reciben acciones. `manager` ahora declara `library`, coherente con su permiso existente en los endpoints de biblioteca. El rol no se acepta del cliente ni del modelo. Sin borrados, despliegues, cambios de roles, cambios de elementos de watchlist ni decisiones de fraude.
  - **Contexto por acción:** el catálogo declara campos y contexto; los generadores cargan referencias de lectura acotadas (máximo 50) y enums: taxonomías existentes, taxonomías para MO, MO para flags, MO/taxonomías para casos similares y metadatos de watchlists sin elementos. Referencias, duplicados, esquema y datos personales se validan en backend.
  - **Ya implementado:** routers de borrador existentes reutilizados; guard nuevo que exige acceso al asistente y escritura de biblioteca; consulta server-side de acciones integrada en el panel; el borrador se presenta en `SideDrawer` con marca ARIA, procedencia, verificaciones y preguntas, y se confirma por endpoint protegido. Los paquetes firmados no se editan en cliente: el usuario pide el ajuste en chat y genera otra propuesta.
  - **Cobertura ampliada:** `agent-assistant-base-real.spec.ts` ahora cubre creación/confirmación de los cinco tipos, marca ARIA y denegación para `release_manager` (requiere credenciales `E2E_RELEASE_MANAGER_*`). Se añadieron pruebas backend de catálogo por rol, intento de suplantación y bloqueo de los cinco endpoints.
  - **Seguimiento pendiente:**
    1. [ ] Completar #17 migrando nueva configuración y ejecutar sus E2E.
    2. [ ] Decidir si se amplía #18 más allá de las cinco acciones listadas; para cada familia nueva, implementar contexto, permiso y pruebas antes de publicarla. En particular siguen fuera pruebas/datasets/uploads, modelos/entrenamiento, catálogos de configuración, canales, bibliotecas de datasets, instancias de Vector Store, fraude, roles, despliegues y backups.
    3. [ ] Añadir pruebas de contexto de generación para cada tipo (el contexto de taxonomías/enums para modus operandi ya tiene prueba; los otros contextos requieren cobertura directa).
    4. [ ] E2E actualizado, **pendiente de ejecución por instrucción del usuario**: reconstruir stack y correr la spec real vía nginx `http://localhost`, incluida la variante por rol cuando existan credenciales.
    5. [x] Verificado: `make lint`, `make test-architecture` (253), pytest focalizado (27), `make test-api-contracts` (191 operaciones), `make project-graph`/check, ESLint focalizado y `make build` del frontend.
  - **Criterio funcional:** cada acción publicada aparece solo para roles autorizados, obtiene contexto de lectura, valida el borrador y requiere confirmación protegida. Queda seguimiento de E2E real indicado arriba.

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

- [x] **#19 [D][I] Grafo de evolución de versiones/ramas de configuraciones** (estilo GitGraph): ver cómo han evolucionado las ramas, qué cambios se promovieron a producción y cómo se propagaron a las ramas posteriores hasta la actual.
  - **Avance (E2E escrito, sin ejecutar):** cada versión guarda `parent_ref`; `GET /configurations/graph` (solo lectura) devuelve cada versión con su padre y `promotion_comment` (mensaje de la solicitud de despliegue aprobada, solo si la versión fue promovida y existe). Configuración dibuja el grafo con `@gitgraph/react`: solo la familia (raíz, versiones y ramas) de la configuración elegida en el selector superior, con un carril por linaje, color por estado (activa, promovida, probada, borrador), leyenda y panel de detalle con el comentario de promoción. Decidido: sin referencias a hipótesis/experimento (fuera de alcance); el `Scan` de `list_all_versions` se acepta por ahora (tabla pequeña). Pruebas: unitarias del caso de uso y del mapper; E2E `e2e/configuration-graph-real.spec.ts` (estructura y detalle) y aserción de comentario de promoción en `configuration-deploy-real.spec.ts`; ambos incluidos en `make e2e-configuration-parallel`. **Pendiente:** correr esos E2E contra el stack reconstruido (`make e2e-configuration-parallel` o `make e2e-selected-real E2E_TEST_FILES=e2e/configuration-graph-real.spec.ts`) y verificar a ojo el dibujo; la promoción exige `E2E_DEPLOY_CONFIGURATION_ID`/`E2E_DEPLOY_VERSION`.
  - **Estado actual del modelo:** `ConfigurationRecord` tiene `configuration_id` (linaje) + `version` (incrementa por edición), `active`, `ever_activated`, `activated_at`, `created_at`, `created_by`. **No hay puntero a padre ni a rama**: el historial es lineal por linaje y no se sabe de qué versión/configuración se derivó otra.
  - **[D] Decidir qué es una "rama":** cada linaje (`configuration_id`) es una rama y se bifurca al duplicar una configuración. Las candidatas paralelas parten de un mismo baseline mediante `parent_ref`; no se define semántica de merge.
  - **[I] Backend:** guardar `parent_ref` (`ConfigurationRef`: `configuration_id` + `version`) al crear una versión nueva o al duplicar; para las existentes, dejar `None` (inicio del grafo) o inferir el padre lineal (`version - 1`). Registrar eventos de promoción (activación a producción) con fecha y autor (hoy sólo hay `activated_at`/`ever_activated`, que se sobrescribe, no un historial). Endpoint de solo lectura que devuelva nodos y aristas (sin `Scan`; indexar por linaje). Permitir que la ejecución de investigación refiera versiones candidatas y su baseline mediante referencias explícitas a experimento/hipótesis; esas referencias sirven para navegar y visualizar, no crean pertenencia entre la configuración y el esquema ni cambian la semántica del linaje.
  - **[I] Frontend:** render del grafo con SVG propio o una librería ligera (p. ej. `@gitgraph/react`); nodo = versión, color = estado (activa, promovida alguna vez, borrador/probada), marcador de promoción a producción, clic abre el detalle. Mostrar referencias disponibles a hipótesis/experimento y decisión de promoción. Ubicarlo en Configuración (junto a `ConfigurationVersionGuide`).
  - **Límite:** "propagación de cambios" como en Git (merge) no existe; se mostraría **linaje**, no diffs fusionados. Si se quiere ver qué cambió entre nodos, es un diff de configuraciones aparte.
  - E2E real sobre el grafo.

## 9. Diagramas de workflow dentro de la plataforma

- [x] **#20 [D][I] Llevar a la plataforma los diagramas de `docs/presentacion/aria_capacidades.html`** (roles por persona, etapas del pipeline, flujo). Ese HTML ya tiene ~68 SVG; reutilizarlos como componentes React compartidos (`WorkflowDiagram` y variantes), no redibujar. Cada diagrama debe ser **vivo cuando haya datos** (resaltar la etapa en curso, conteos por etapa) y **estático explicativo** en los demás casos. Colapsables, para no volver a alargar las páginas (ver #11).

  - **Avance (2026-10-25):** hechos Detalle de alerta, Cola (`QueueFunnelDiagram`, conteos vivos de `listAnalystQueue`/`listInProcessAlerts`), Dashboard (`LifecycleDiagram` con conteos de `getLiveAlertFunnel`) y Configuración (flujo de revisión, XGBoost, resolución). Registrados en el grafo del proyecto (concepto `diagramas-del-flujo`). E2E real `make test-e2e-capability-help` pasó por nginx. **Ítem cerrado por decisión del usuario (2026-10-25)** con el alcance entregado; el E2E ajustado (conteos contra la API) aún no se ha corrido. Quedan fuera, como seguimiento opcional: Monitor, Configuración→despliegue, Biblioteca, Modelos, Histórico, Testing, Asistente/Optimizador/Orquestador, Roles, Onboarding y Backups.

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

- [x] **#21 [D][I] Event API (componente nuevo).** Servicio independiente para recibir las alertas filtradas por FRM.
  - **Esquema abierto:** sin restricciones de esquema en la entrada; la validación se hace en el preproceso y varía según el esquema de entrada activo (`AlertSchemaVersion`). El Event API no valida contenido (sólo lo mínimo para aceptar: JSON bien formado, tamaño máximo, autenticación del emisor).
  - **Sólo hace push** del evento a la **cola de producción**. Nada de testing, ni rutas de prueba, ni lógica de negocio. Los tests/simulaciones siguen su propio camino (simulador) y nunca pasan por aquí.
  - **[D resuelta]:** contrato `{alert_id, event_id}`; `POST /api/event/events` responde `202` con `event_id` como recibo. Idempotencia por `event_id` por 30 días en Redis; repetir el mismo ID para otra alerta responde `409`. Si issuer o cola no están disponibles, responde `503` para que FRM reintente. La cola se configura como producción y no se comparte con test/simulación.
  - **Implementación parcial:** servicio independiente `event-api`, Docker Compose, Dockerfile local/OKD, Route TLS, OIDC por issuer/audience/JWKS y client ID configurables, límite de tamaño y publisher Celery a la cola `production_events`; detalle en `docs/EVENT_API.md`. Falta configurar el issuer OIDC corporativo en OKD y conectar el worker consumidor con #22.
  - E2E local agregado y ejecutado ✅ 2026-10-24 (`make e2e-event-api-local`): token ausente/inválido, aceptación y presencia del mensaje solo en la cola productiva, reintento idempotente, JSON inválido, límite de tamaño y cola no disponible con retry. La cobertura ya incluye campos adicionales de FRM ignorados y conflicto al reutilizar `event_id`; **pendiente correr de nuevo** tras este cambio. Verificar entrega/consumo por worker cuando se conecte el preproceso #22.

- [~] **#22 [D][I] Preproceso: de alerta resumida a alerta enriquecida.** En producción no llegará la alerta completa sino la **alerta resumida (básicamente un id)**. El preproceso debe: (1) hacer fetch de la información de la alerta, (2) hacer fetch de **otras fuentes** para complementarla, (3) validar contra el esquema activo y (4) pasar a las etapas siguientes.
  - **Sólo producción:** el enriquecimiento ocurre únicamente en el flujo de producción, cuando una alerta llega a ARIA desde el Event API. Ahí la alerta trae sólo la información base (básicamente el id), y los llamados a los servicios externos son lo que la completa; sin ellos no hay datos suficientes para las etapas siguientes. En testing/simulación/datasets la alerta ya viene completa: **no se llaman esas fuentes** (el preproceso se salta el enriquecimiento o usa adaptadores que no salen a servicios reales). Hacer explícito ese modo (p. ej. un origen `production` vs. `test` en el evento/ejecución) en vez de depender de qué campos vengan.
  - **Estado actual:** el preproceso obtiene el JSON canónico con un puerto de Alert API por `alert_id` y camina sus campos con el esquema activo de ARIA, sin imponer otro contrato de payload. Los puertos de perfil, cambios personales, historial y ARIC complementan después los datos y reintentan (`MAX_FETCH_ATTEMPTS = 3`).
  - **Avance 2026-10-25:** el origen ya distingue producción de test/simulación/optimizador; sólo producción ejecuta enriquecimiento externo. El worker consume `events.production.receive`, busca el registro por `alert_id`, y el adaptador lee su JSON canónico persistido antes de validarlo con el esquema activo. E2E pendiente por instrucción del usuario.
  - **Modelarlo en el preproceso (la lambda/tarea de preproceso), no en la API de alertas** (decisión explícita). Las fuentes son conectores intercambiables (un puerto por fuente, adaptador por tecnología), configurables, agregables sin tocar casos de uso.
  - **[D resuelta parcialmente]:** contrato resumido `{alert_id, event_id}`. Ante fallos, reintentar de forma acotada; si falla una fuente necesaria para campos obligatorios del esquema activo, fallar el preproceso; si falla una fuente opcional, continuar y marcar el enriquecimiento como incompleto. Sigue pendiente definir orden/paralelismo, timeouts y clasificar qué fuentes alimentan campos obligatorios u opcionales.
  - **Integración pendiente:** Alert API debe persistir el JSON canónico en el registro asociado a `alert_id` antes de publicar el evento. Los adaptadores ARIC/Host actuales siguen siendo mock; conectar sus servicios reales cuando estén disponibles.
  - **[V] Verificar:** cómo se ve en el workflow y el monitor (estado y latencia del paso de preproceso por fuente) y que las rutas de datos (`schema_version_at_creation`) queden registradas.
  - Actualizar el diagrama del pipeline (#20) para mostrar Event API → cola de producción → preproceso (enriquecimiento) → etapas siguientes.

- [~] **#23 [D][I] Preparación reproducible de datasets para diagnóstico y experimentos.** Crear particiones de entrenamiento, validación, calibración y prueba a partir de un dataset cargado, revisando sus parámetros y conservando una copia reproducible para evitar fuga de datos entre etapas. Si la fuente es producción, obtener primero la muestra madura mediante el sampler existente y aplicar después la partición. No leer directamente índices de creación para saltarse la ventana de madurez, que debe ser configurable.
  - **Avance 2026-10-25:** `POST /datasets/{name}/splits` crea una copia derivada con etiqueta de partición, hash de contenido, semilla, proporciones y estratos; los registros se asignan a una única partición y el dataset derivado rechaza append. El worker de modelos respeta esas particiones. Pendientes: experiencia frontend para revisar/confirmar parámetros y E2E real (en espera de indicación del usuario).
  - Guiar al usuario para definir y revisar los parámetros de separación: categoría/estratos, distribución objetivo, proporciones, semilla y columnas relevantes. Mostrar conteos y distribución resultante antes de confirmar; guardar parámetros, semilla, mapeos y referencia al snapshot para reproducir el split.
  - Mantener entrenamiento/validación para diagnóstico e iteración y reservar la partición final para la evaluación final, evitando que el diagnóstico la consuma. Comparar baseline y candidata sobre la misma muestra y partición.
  - Registrar el esquema usado como contexto de validación/evaluación, no como relación de pertenencia con la configuración. Ante incompatibilidad con otro esquema, emitir alertas explicativas.
  - El worker autorizado procesa filas y devuelve agregados con soporte mínimo; no exponer filas al LLM, chat ni insights. Incorporar límites de costo y volumen.
  - Coordinar el contrato y la experiencia de configuración del split con el backlog de datasets; cubrir fuentes cargada, catálogo y producción madura con E2E real.

- [x] **#24 [D][I] Actualizar observabilidad para el ciclo científico del optimizador.** La observabilidad actual corresponde a una versión anterior del agente y no representa el andamiaje de sesiones, hallazgos, hipótesis, experimentos, verificaciones y decisiones que estamos incorporando.
  - Inventariar eventos y paneles actuales y definir instrumentación para el ciclo completo: etapa/estado, duración, espera en cola, reintentos, bloqueos y resultados inconclusos; mostrar concurrencia de experimentos y workers, presupuesto agregado, fuente y particiones del dataset, versión de esquema validada y límites/uso de embeddings.
  - Correlacionar sesión, hallazgo, hipótesis, experimento, ejecución y promoción en trazas, logs y auditoría mediante referencias opacas. No usar esos IDs como dimensiones de métricas: mantener atributos métricos de baja cardinalidad y respetar los límites de privacidad (sin filas, PII ni prompts).
  - Mostrar la trazabilidad de evidencia y decisiones desde el monitor y los diagramas vivos (#20), incluyendo cuándo el agente continúa autónomamente y cuándo queda bloqueado esperando aclaración humana.
  - Mantener OTLP como contrato de telemetría, auditoría de negocio mediante `AuditPort` y métricas de negocio agregadas según el contrato existente; no duplicar rollups como telemetría.
  - Cubrir el ciclo de vida y las restricciones de cardinalidad/privacidad con E2E real a través de nginx.
  - **Hecho 2026-10-26:** línea de tiempo `agent_events` con eventos por experimento, trazabilidad sesión → candidato → experimento → conclusión → release en `optimization_runs` y en el audit log, métricas OTLP `aria.optimizer.*` de baja cardinalidad y `agent_tool_calls`. Monitor → pestaña «Optimizador» (`GET /agent/optimizer-status`, permiso `monitor`): sesiones por estado, candidatos en paralelo y ejecuciones activas frente a sus topes, esperas por motivo, presupuesto agregado, experimentos por resultado y muestras maduras en uso (periodo, madurez, particiones, versión de esquema). E2E `optimizer-center-real.spec.ts` comprueba que la respuesta no contiene identificadores de sesión. Sin datos de uso de embeddings por sesión: el optimizador no los registra todavía.

- [x] **#25 [D][I] Dejar listo el agente optimizador: estructuras, runtime, subagentes, trazabilidad e interfaz.** Plan acordado 2026-10-26; todo entra en esta ronda (incluye #24 y el replay real del pipeline). Se ejecuta por etapas; cada etapa deja pruebas verdes antes de seguir.
  - **Decisiones (2026-10-26):** (1) tabla nueva **`agent_events`** (línea de tiempo append-only por sesión: `seq`, tipo, referencias opacas, resultado, código de razón seguro) para seguir a cada agente. Si el agente interviene un objeto de producción, el cambio se registra **en ambas**: `agent_events` **y** el audit log (`AuditPort`). (2) Quien actúa ante un fallo es el **Channel Manager**, y los fallos **no son autogestionables**: si falta contexto o se excede el tope de iteraciones/presupuesto, el agente se detiene en un estado bloqueado, informa al usuario y espera que apruebe más (iteraciones, presupuesto o contexto). (3) El replay real (perfilamiento, LLM, revisión adversarial) entra en esta ronda. (4) El **Centro del optimizador** se quita del panel del chat asistente y pasa a una **pestaña junto a las configuraciones del perfil Channel Manager**.
  - **Etapa 0:** reproducir como test el fallo de H9 (lease vencido con iteración y experimento `RUNNING` sin evidencia; caída del frontend durante la limpieza).
  - **Etapa 1 · estructuras:** `agent_events`; `agent_findings` y `optimizer_insights` (índices `ScopeStatusIdx`/`StatusReviewIdx`, mínimo 30 casos, sin filas por alerta); `agent_experiments` unificado (hipótesis, iteración, protocolo, pins, estado, verificaciones, `failure_reason`); `agent_links` escrito siempre; BD.5 (manager, respaldos, `e2e_state_cleaner`, OKD, limpieza por `expires_at`) y BD.6 (arquitectura + fuga con valores señuelo).
  - **Etapa 2 · runtime:** partir `OrchestrateAgentIterationUseCase.execute` en pasos idempotentes y reanudables, cada uno con su evento; recuperación idempotente del orquestador; catálogo de errores (mensaje en español, reintentable o no, quién aprueba); estado `WAITING_USER`/bloqueado por falta de contexto, tope de iteraciones o presupuesto, con aprobación de más; batería de contrato común para cada subagente (configuración, Biblioteca, Vector Store, XGBoost); heartbeat, estancamiento y coste anómalo; replay real del pipeline y promoción del conjunto versionado completo (modelo, configuración, Biblioteca, Vector Store) en H11/H12.
  - **Etapa 3 · observabilidad (absorbe #24):** spans con referencias opacas, métricas de baja cardinalidad, correlación sesión → hallazgo → hipótesis → experimento → ejecución → promoción, pestaña del optimizador en el Monitor, pruebas de fuga.
  - **Etapa 4 · interfaz:** Centro del optimizador en pestaña de Configuración (perfil Channel Manager), con veredicto arriba (corriendo / bloqueado esperando aprobación / falló con razón y acción / inconcluso), línea de tiempo desde `agent_events`, tablero de hipótesis, baseline vs candidato, trazabilidad insight → hipótesis → experimento → decisión, ciclo vivo (#20), runs de subagentes con duración/coste/error legible, aviso de salud, estados de carga/vacío/error. Retirarlo del panel del chat.
  - **Avance 2026-10-26:** etapas 0 a 4 implementadas y commiteadas. Backend: `agent_events`, `agent_findings`, `optimizer_insights`, `AgentTimeline` (registro doble en `AuditPort` para releases y borradores aplicados), `execute` partido en fases, recuperación idempotente (cierra iteraciones y experimentos huérfanos), estados bloqueados `WAITING_USER` con `ResolveAgentBlockUseCase`, regla de costo anómalo, memoria del optimizador con mínimo de 30 casos, catálogo de fallos en español, métricas `aria.optimizer.*` y API `overview/events/findings/memory/block-resolve/failure-catalog`. Frontend: Centro del optimizador en Configuración → pestaña «Optimizador» (solo Channel Manager), retirado del chat. Pruebas: 1.728 unitarias, batería de contrato por especialista, E2E `optimizer-center-real.spec.ts` (11 escenarios sembrados, ~1 min) y ciclo real `agent-optimizer-real.spec.ts`. Verificación visual con capturas de Playwright de los 8 estados.
  - **Pendiente de #25:** (a) replay real del pipeline en la validación retrospectiva de H12 (hoy el API usa el scorer del MCP; requiere ejecutarla en el worker con un registro `RUNNING`); (b) promoción del conjunto versionado completo (hoy solo modelo; requiere enrutar configuración/Biblioteca/Vector Store por alerta en canary); (c) smoke H9 real con 30 alertas.
  - **Pruebas:** sin E2E largos. Pirámide: unit/property de la máquina de estados, contrato de subagentes y repositorios contra DynamoDB Local, y E2E de navegador por nginx con sesiones **sembradas por API** en cada estado (corriendo, bloqueada, fallida, inconclusa, completada, lease vencido), cada uno < 90 s y en paralelo con usuarios aislados. Ciclo real con subagente stub y fixture de 30 alertas. Un único smoke con LLM real, etiquetado y fuera del flujo normal. Cada E2E comprueba que lo que muestra la UI coincide con `agent_events`/registros y que un fallo inyectado aparece con razón y acción sugerida. Objetivo: conjunto del optimizador ≈ 8 min.

- [x] **#26 [D][I] H12: validación retrospectiva con el replay real y promoción del conjunto versionado completo.** Pendiente de #25 (2026-10-26).
  - **Hecho 2026-10-26 (decisión: flujo existente):** `POST /agent/releases/retrospective-validations` responde 202 con la validación en `RUNNING`; la tarea `agent.validate_retrospective` la completa en el worker con el replay real del pipeline (`WorkflowAgentPipelineScorer`) y la deja `PASSED` o `FAILED` con su código; el panel de releases y `e2e_agent_h12_local.mjs` la siguen por `GET`. Los releases aceptan configuración, Biblioteca y Vector Store: al aprobarse, la configuración se entrega como solicitud de despliegue (aprueba manager/release manager), el Vector Store usa su promoción y la Biblioteca queda para revisión manual (no es versionada); cada entrega queda en el audit log y en la línea de tiempo. El modelo sigue con sombra y canary; sin cambio de modelo no hay sombra y el release queda completo al aprobarse. Corregido además: ganadores, conclusiones y memoria leían las métricas en un formato distinto al que publica el evaluador (`metrics.candidate`, `sample.eligible_count`).
  - **Replay real:** hoy `POST /agent/retrospective-validations` corre en el API con el scorer del MCP (solo modelo), mientras el experimento se midió en el worker con el replay del flujo real; la evidencia puede no coincidir. Ejecutarla en el worker con un registro `RUNNING` (nuevo estado de `RetrospectiveValidationStatus`), respuesta 202 y sondeo desde `AgentReleasePanel`; reescribir `e2e_agent_h12_local.mjs`.
  - **Promoción completa:** `ManageAgentReleaseUseCase` exige que configuración, Biblioteca y Vector Store no cambien (`h12_model_only_v1`). Enrutar esos tres componentes por alerta en canary (bucket estable) en el flujo de revisión, con shadow y rollback, y registrar cada paso en `agent_events` y en el audit log.
  - **Decisión tuya:** si la promoción de configuración sigue por el flujo de solicitudes de despliegue existente o por el canary del release.
- [x] **#27 [I] Smoke real del optimizador (H9) con muestra de 30 alertas.** Los dos intentos del 2026-10-23 no se declararon verificados. Con la recuperación idempotente ya implementada, repetir `make e2e-agent-h9-local` con muestra aislada de 30, tres workers de prueba y comprobar cierre y restauración si cae el frontend (puerto 80).
  - **Verificado 2026-10-26:** `E2E_AGENT_FAST=1 E2E_PRESERVE_DATA=1 E2E_AGENT_TEST_WORKERS=8 make e2e-agent-h9-local` pasó por nginx con LLM y workers reales, sobre la muestra final de 41 casos de H8: especialista `xgboost` verificado, replay de línea base y candidato, experimento `REJECTED_GLOBAL_CONSTRAINT`, cierre de la sesión, auditoría paginada y Centro del optimizador (Corrida, salud y línea de tiempo).
  - **Fallos encontrados y corregidos en el camino:** la limpieza de sesiones sembradas solo leía la primera página del scan y dejaba sesiones `ACTIVE` ocupando el cupo (`8b0c261`, y el spec limpia al arrancar); una alerta que agota el feedback adversarial tumbaba todo el candidato y ahora cuenta como sin decisión (`e2b05eb`); el cliente de Azure OpenAI no tenía timeout y una llamada colgada retenía los workers ~15 min, ahora `OPENAI_REQUEST_TIMEOUT_SECONDS` = 120 (`88fa992`); el especialista reintenta una vez una propuesta inválida (`63e1fe1`); el script acepta una corrida sin ganador que espera contexto y compara etiquetas de UI sin importar mayúsculas (`9f5e5bc`, `fd4d3db`); H9/H11 dimensionan sus workers con `E2E_AGENT_TEST_WORKERS` (`36b0c14`).
  - **Abierto, decisión tuya:** (a) el reconciliador cuenta el timeout de atascado (`CELERY_STUCK_TASK_TIMEOUT_SECONDS`, 900 s) desde que la tarea se encola y sobrescribe workflows que siguen corriendo; con 3 workers y 123 replays falló la evaluación. Propuesta: separar espera en cola de ejecución y no tocar workflows con avance reciente. (b) Con `optimizer_stop_on_critical_failure` cualquier error detiene la sesión, aunque el catálogo marque el código como reintentable. (c) El replay corre con `max_feedback_iterations=1`: ~45 % de las alertas quedan sin decisión por el revisor adversarial. (d) Los casos sintéticos de H8 no traen señal (montos y canal iguales al historial, flags ARIC nulos): el clasificador responde `unknown` en todos y línea base y candidato salen con precisión y recall 0, así que el smoke prueba la tubería pero no calidad; además, precisión con cero predicciones positivas debería reportarse como no definida.
- [ ] **#28 [I] Deuda de pruebas y entorno detectada en #25.**
  - ✅ Los 14 tests de `test_alert_review_workflow.py` ya no necesitan `minio`: un fake del origen de payload (`ef9b98e`).
  - ✅ `hypothesis==6.170.9` (versión del lock) instalado en el entorno local; la suite completa pasa (1.783).
  - ✅ `optimizer-center-real.spec.ts` (worker caído): el barrido de 30 s puede recuperar la sesión antes de mirarla; el spec reintenta hasta 4 sesiones y además comprueba la recuperación por API, así que es estable. Las sesiones sembradas `ACTIVE` cuentan para el tope de sesiones concurrentes; el spec las limpia al terminar.
  - Un `ruff format` accidental dejó ~37 archivos de `src/application` y `src/domain` con cambios solo de formato sin commitear: revertir con `git restore`.
  - Inspección visual del Centro del optimizador en Chrome real (hasta ahora solo capturas de Playwright; requiere que inicies sesión).
  - Corrida completa `make e2e-all-local` posterior a #25 (2026-10-26, 10,1 min): 85 pasan y 13 fallan. 11 son de `optimizer-center-real.spec.ts` por el sembrador, que heredaba `GENAI_ENVIRONMENT=local` del runner (corregido en `6252038`; el spec pasa 11/11 con ese entorno). Los otros dos no vienen de #25: `agent-assistant-base-real.spec.ts:513` llama a `login`, que no está definida en el spec, y E06 `event-simulation-real.spec.ts:215` no recibe `field_specs.eventId` del escenario. **2026-10-26:** corregidos en el frontend `7b275b5` (helper `login` definido, el test pasa; E06 espera la respuesta de la siembra antes de editar campos, y pasa completo con el stack libre).

- [x] **#29 [D][I] `OptimizationRun`: una sola macroestructura para la corrida del optimizador, con experimentos en paralelo.** Acordado 2026-10-26.
  - **Estructura:** tabla `optimization_runs`, una partición por corrida (`run_id` = sesión) con un ítem por nodo: raíz `RUN` (configuración base del optimizador, línea base fijada, presupuesto y topes, insights generales y de memoria, ganadores, configuración ganadora y estrategia), `CAND#<id>` (hipótesis, insights propios, estado y conclusión dentro del candidato, no como entidad aparte) y `EXP#<id>` (pila candidata, resultados, verificaciones y hallazgos). Hipótesis, experimentos y hallazgos dejan de vivir en tablas propias: sus puertos pasan a escribir en esta estructura.
  - **Eventos:** solo referencias por llave. La raíz apunta a la línea de tiempo general de la sesión y cada experimento a su propia línea en `agent_events` (llave `<sesión>#exp#<experimento>`), para seguir experimentos paralelos sin mezclarlos.
  - **Paralelización:** hasta 3 experimentos simultáneos por sesión si son independientes (cambian componentes distintos y ninguno depende del otro), 2 sesiones y 6 experimentos globales. Cada uno corre su candidato contra la misma línea base y la misma muestra madura; si varios ganan, el experimento de combinación va después, en serie. Presupuesto repartido por candidato.
  - **Trazabilidad pendiente incluida:** acciones del usuario (iniciar, pausar, reanudar, cancelar, confirmar o rechazar insights) en `agent_events`; llamadas a herramientas y al LLM con duración, tokens y costo.
  - **Vista:** `GET /agent/optimization-runs/<id>` devuelve el árbol completo; el Centro del optimizador lo muestra con ganadores y experimentos en paralelo.
  - **Avance 2026-10-26:** implementado. Estructura `optimization_runs` con raíz, candidatos (con conclusión), experimentos (con su línea de eventos) y hallazgos; tablas `agent_hypotheses`, `agent_experiments` y `agent_findings` absorbidas. Runtime: planificación de hasta 3 candidatos independientes por tick, tarea `agent.run_candidate` con heartbeat de 30 s, combinación de ganadores en serie, ganadores y estrategia en la raíz, fin con ganadores o espera de contexto. Ajuste `optimizer_max_parallel_experiments` (3) y topes por defecto de 2 sesiones y 6 ejecuciones. Trazabilidad: `agent_tool_calls` por especialista y eventos `user_action` de sesión e insights. Pestaña «Corrida» en el Centro del optimizador. Pruebas: 9 unitarias del modo paralelo, recuperación con lease vivo y E2E sembrado `parallel`. Verificado 2026-10-26 tras reconstruir el stack: capturas de la pestaña «Corrida» (terminada con dos ganadores y su combinación, y tres candidatos en paralelo), `optimizer-center-real.spec.ts` 12/12 y `agent-optimizer-real.spec.ts` 1/1 por nginx, 1.749 unitarias. El paralelismo con LLM y workers reales queda para el smoke #27.

## 11. Panel del asistente: reducir ruido visual

- [x] **Insights y contexto del grafo** — ✅ Hecho 2026-10-25: las propuestas de insight quedan plegadas por defecto y sus acciones siguen disponibles al expandirlas; el panel ya no muestra la lista «Contexto usado», pero conserva los chips de navegación. E2E real `agent-chat-dense-real.spec.ts`: 3/3 pasaron por nginx.
