# Backlog: agente orquestador de ARIA (loop del channel manager)

## Guía de retoma (leer primero)

**Estado (2026-10-19).** Wave 0 y H1–H4 permanecen integrados. H5 corregido
quedó integrado en `ad78bef` después de restaurar la primera entrega revertida
(`fc6d33a`) e incorporar el generador JSON estructurado (`8c1dcdc`). La causa
del `409 DRAFT_POLICY` post-merge anterior era el contrato de chat incompatible
con la salida JSON del generador; la corrección separa ambos adaptadores y
clasifica una salida inválida como indisponibilidad de generación. Verificación
integradora H5: lint Ruff/mypy 0/0, arquitectura 227/227, pytest focalizado
18/18 y E2E real reconstruido por nginx pasó create/update, verificaciones,
diff, base_version y auditoría.

H6 quedó integrado en `a08e019`. La selección configurable cubre los cuatro
campos del esquema: marca inicial, fecha inicial, etiqueta vigente y fecha de
última marcación; también configura el mapeo a fraude/no fraude. Verificación
integradora H6: lint Ruff/mypy 0/0, arquitectura 233/233, pytest focalizado
20/20 y Playwright real por nginx 1/1. El merge conservó la limpieza E2E de
tablas del chat H4 y del muestreador H6. Los baselines de lint no crecieron.

Queda pendiente la decisión 8 y las decisiones técnicas B0.2–B0.4 antes de
H8. H7 en adelante no está autorizado por estas integraciones. FP0/FP1 de la
pestaña del muestreador se integraron en frontend (`c8eb74c`, `8cf3d2e`) y el
E2E del panel pasó; FP1b/FP2/FP3 del panel conversacional siguen por confirmar.
La suite completa `make e2e-all-local` pasó 27/27 por nginx en la revisión
integradora del 2026-10-20, tras corregir los
fallos reportados anteriormente. E01 tenía dos errores de backend: la
transacción de activación enviaba valores tipados a un cliente boto3 que ya los
serializa, y la aprobación omitía `:pending` de sus valores de expresión. E01
también tenía el botón flotante del asistente encima del CTA; se desplazó cuando
la página tiene barra inferior. E06 requería más de 90 segundos para eliminar
un dataset; su límite de espera E2E ahora es 180 segundos (la tarea terminaba
correctamente). E05 dependía de particiones CSV que no se generaban antes de
la suite; `e2e-all-local` ahora prepara los fixtures reales antes de correr.
Verificación posterior: lint Ruff/mypy 0/0, arquitectura 240/240, pytest de
repositorios de configuración 22/22 y suite completa 27/27. Los baselines no
cambiaron.

**Fuente de etiquetas y volumen (aclaración del usuario, 2026-10-19).** Hoy la
marca vigente está en `tipo`: `ris`/`risk-suspect` se normaliza a fraude y
`no-risk` a no fraude. Una remarcación reemplaza ese valor y actualiza la fecha
de última marcación; la marca y fecha iniciales permanecen inmutables. El
volumen disponible es de unos 50.000 registros maduros por mes, con 2–4 % de
fraude (aprox. 1.000–2.000); aunque existe historia de cinco años, solo se
pueden obtener unos seis meses. El muestreador debe usar ese horizonte
disponible. No se presupone que los nombres de campos sean fijos: en la
configuración, el manager seleccionará los campos desde el pool publicado por
el esquema y definirá/revisará el mapeo de valores de etiqueta. La marca vigente
y su fecha de maduración deben seleccionarse por separado de la marca/fecha
iniciales. `fraud_label_reviews` no se considera historial completo del origen
hasta confirmar que captura todas las remarcaciones externas; eso no bloquea el
muestreo del estado vigente.
El documento nació el
2026-10-13 como "agente de optimización" centrado en XGBoost (commit
`6923c68`) y se reescribió el 2026-10-18 tras una conversación larga con el
usuario. Hay dos registros paralelos: `PENDIENTES.md` §8 y la memoria
`aria-orchestrator-agent-design.md`.

**Qué se quiere construir.** Un orquestador con subagentes que asiste al
channel manager, en dos modos:
- **Asistente**: chat en un panel lateral; el usuario pega texto y el agente
  crea o edita entidades (Biblioteca, configuración del agente, Vector Stores,
  modelos XGBoost) como borradores que el usuario confirma.
- **Optimizador**: ciclo largo que diagnostica, prueba y deja paquetes
  candidatos listos con evidencia. Nunca activa ni promueve nada.

**Cómo trabajar con el usuario** (no volver a preguntar lo decidido):
- Hablar en español. Los términos abstractos le confunden: explicar con un
  ejemplo concreto, paso a paso.
- Decidir de una en una, con una recomendación y opciones claras.
- No hacer commit ni push sin que lo pida. Mantener al día este documento,
  `PENDIENTES.md` §8 y la memoria cuando se tome una decisión.
- Todo cambio de comportamiento exige `make lint`, `make test-architecture`,
  pytest y un E2E Playwright real a través de nginx (`CLAUDE.md`). Los
  baselines de lint y de arquitectura no pueden crecer.

### Decisiones tomadas

| Tema | Decisión | Dónde |
|---|---|---|
| Modos | Un orquestador con dos modos: asistente (primer vertical) y optimizador | Objetivo |
| Aprobación | El agente nunca activa ni promueve. Todo es un paquete candidato versionado que el usuario aprueba | Principio 6 |
| Confirmación | Siempre explícita, antes de toda escritura sobre una entidad viva (crear, editar, eliminar), guardada como auditoría append-only | BM.7 |
| Entrada del usuario | Solo texto pegado en la v1, sin archivos | Dec. 9, 14 |
| Datos personales | Se enmascaran antes del modelo y antes de guardar; el original no se conserva; sin KMS | BM.1, dec. 19 |
| Tamaño y retención | 8.000 caracteres por mensaje (configurable); 2 años para todo el chat | Dec. 13, 19 |
| Alcance del asistente | Biblioteca (crear, editar, proponer eliminar), configuraciones versionadas, Vector Stores y modelos XGBoost. Nunca `OperationalSettings` | Dec. 10, 16, 18 |
| Roles del asistente | Los mismos que crean a mano cada entidad | Dec. 11 |
| Roles del optimizador | Solo `channel_manager` lo activa y decide lo que el agente le escala | Dec. 15, 23 |
| Interfaz | Panel lateral derecho superpuesto en Configuración, Testing, Biblioteca y Modelos. El optimizador es una pestaña (conversación) con su progreso y no bloquea el chat | Dec. 15, 20 |
| Interferencia | Si un optimizador trabaja sobre lo mismo, el asistente muestra un aviso (informativo, no bloquea) | Dec. 16, BM.8 |
| Chat | Polling con `after_seq` | Dec. 12 |
| Prompts del agente | Versionados e inmutables; los gestionan los desarrolladores; sin evaluación previa por ahora; el agente no edita los suyos | Dec. 17, B1.6 |
| Éxito | `fraud_label` una vez pasada la ventana de maduración (única, configurable); las alertas inmaduras se ven en el monitoreo pero no las usan el reentrenamiento ni el agente | Dec. 1, B0.1 |
| Métrica | Precisión y recall por conteo; se maximiza el recall con un piso de precisión configurable | Dec. 1, 2 |
| Muestreador | Componente nuevo: toma alertas maduras, disparo semanal por defecto, muestra de un periodo anterior a la ventana, guardada como dataset del catálogo | Fase S, dec. 21, 22, 24 |
| Menú de configuración | Pestaña "Asistente y optimizador" en `/configuracion`, editable solo por `release_manager` y `manager` | Dec. 23 |

### Supuestos míos que el usuario no confirmó

Revisarlos antes de implementar; el usuario puede corregirlos.
1. La confirmación debe ser una acción en la interfaz; un "sí" escrito en el
   chat no cuenta.
2. El agente nunca edita sus propios prompts, límites, presupuesto ni
   verificadores (principio 10).
3. Los parámetros viven en un singleton nuevo, `AssistantOptimizerSettings`, y
   no en `OperationalSettings`, porque este ya tiene `agent_enabled` (agente de
   revisión de alertas). La ventana de maduración sí queda en
   `OperationalSettings`.
4. El `channel_manager` puede elegir el alcance y dejar notas al activar el
   optimizador, y ve el presupuesto y los límites vigentes como resumen de
   solo lectura.
5. "Una vez por semana" se entendió como el disparador periódico; los demás
   (volumen, estadístico, manual) existen pero vienen apagados.
6. Nombres de tablas, claves, índices, endpoints y topes del modelo de datos son
   propuesta mía; no existen en el repo.
7. El dimensionamiento de mensajes (unos 9 KB cada uno, 6,5 GB en dos años en
   el peor caso) es una estimación, no una medición.
8. Las acciones del asistente tienen los mismos permisos que la creación
   manual, y el panel aparece según `ROLE_NAV`.

### Lo que no se verificó en el código

- Dónde se arma hoy el dataset de entrenamiento y si ya filtra por madurez. El
  usuario confirmó que el filtro no existe.
- Si el flujo de entrenamiento consume sin cambios un dataset del catálogo
  generado por el muestreador (cuatro particiones).
- Qué rol aprueba hoy la activación de una configuración en el flujo de
  solicitudes de despliegue (pesa en la decisión 5).
- Las guías del frontend (`frontend_mockup/CLAUDE.md`, `AGENTS.md`,
  `CONTRIBUTING.md`) y si el panel de operación ya tiene historial de cambios.
- Si OKD tiene cifrado de tablas o KMS: es un tema de plataforma, aparte.
- Que las tablas de #22 ya estén aprovisionadas en OKD (siguen pendientes).

### Decisiones abiertas

- **2 (decidida 2026-10-18):** tope de **50 USD y 12 horas por sesión**,
  optimizador apagado por defecto, y parada ante el primer fallo crítico. El
  escalamiento queda como dato informativo.
- **3 (decidida 2026-10-19):** unos 50.000 registros maduros al mes, 2–4 %
  fraude; existen cinco años, pero solo se pueden obtener unos seis meses. El
  manager selecciona los campos desde el pool definido por el esquema y
  configura el mapeo de valores de etiqueta.
- **4 (decidida 2026-10-19):** al alcanzar el tope vigente, la sesión se pausa.
  El `channel_manager` puede autorizar topes adicionales explícitos; cada
  autorización añade presupuesto al límite vigente y se registra en auditoría.
  Al agotar el nuevo tope vuelve a pausarse. No hay renovación automática; el
  máximo de ampliaciones se controla con `optimizer_max_budget_renewals`.
- **5 (decidida 2026-10-19):** el `channel_manager` aprueba o rechaza el
  paquete de resultados completo. La promoción a producción es un paso aparte
  y requiere aprobación de `manager` o `release_manager`.
- **6 (decidida 2026-10-19):** los diagnósticos agregados se muestran por
  segmento; solo se publican métricas de un segmento cuando contiene al menos
  30 casos.
- **7**: qué insights persisten entre sesiones y cuáles caducan.
- **8**: qué subagente del optimizador va primero.
- **B0.2, B0.3 y B0.4**: política de datos y presupuesto, contrato de salida
  segura y alcance por entidad. Son trabajo de definición, no preguntas.
- Detalle técnico: qué versiones del esquema de alerta son compatibles (BS.3).

Para construir el **modo asistente** no queda ninguna decisión abierta.

### Mapa del documento

Objetivo y principios → Fase 0 (decisiones) → Fase 1 (columna vertebral) →
Fase 2 (verificadores y diagnóstico) → **Fase S** (muestreador) → Fase 3
(orquestador) → Fase 4 (chat e insights) → **Fase A** (modo asistente) →
Fases 5 a 8 (subagentes, UI, operación, validación) → **Modelo de datos y
runtime** → **Configuración del asistente y del optimizador** → **Orden de
implementación** → **Planificación de frontend** → Decisiones pendientes.

## Objetivo

Construir un agente de ciclo prolongado que haga las labores de un channel
manager: configurar el agente de revisión de alertas, probarlo, diagnosticarlo
y dejar todo listo para promover. Tiene una pieza central, el **orquestador**,
que llama subagentes especialistas por área. El usuario conversa con el
orquestador para darle insights y dirección.

El mismo orquestador opera en **dos modos**:

- **Modo asistente** (primer vertical): sesión corta a petición del usuario
  ("te mando esta información, crea un modus operandi"). Un subagente
  generador produce un borrador de entidad, verificadores deterministas lo
  revisan y el usuario lo edita y aprueba. No hay optimización ni ciclo largo.
- **Modo optimización**: el ciclo prolongado descrito en las fases siguientes.

Ambos comparten sesión, subagentes, paquete candidato, chat, insights,
autorización y aprobación humana. El modo asistente se construye primero
porque ejercita toda la columna vertebral sin requerir la función de
efectividad global ni el presupuesto renovable.

El agente puede crear y modificar cualquier artefacto que el channel manager
gestiona, incluidas entidades nuevas como modus operandi. Todo lo que produce
es un **paquete candidato versionado**. El usuario revisa y aprueba; el agente
no activa ni promueve nada por cuenta propia.

Este backlog se basa en el estado observado de `backend` y `frontend_mockup`.
No cambia contratos actuales hasta que se acuerden las decisiones del final.

## Estado actual relevante

- El flujo de revisión tiene diez pasos potenciales, saltos por reglas y
  detector, y loops adversariales. XGBoost es una señal del detector o del
  clasificador, no una etapa independiente.
- El backend entrena XGBoost de forma asíncrona en un worker separado. Un modelo
  entrenado no se reentrena: cada candidato requiere un modelo nuevo.
- El informe de entrenamiento incluye cuatro particiones, métricas por umbral,
  curvas, importancia de variables, parámetros efectivos y hash del dataset.
- Las pruebas del pipeline computan métricas de duración por etapa, acuerdo con
  marcación de analista y comparación con desenlace maduro. Los detalles de
  casos pueden incluir datos de entrada/salida.
- Configuraciones (versionadas) y Vector Stores (build → promote) tienen flujos
  de prueba o promoción. La activación de modelos y la promoción de Vector
  Stores son acciones explícitas separadas.
- **No todo lo que gestiona el channel manager es versionado:**
  - La Biblioteca (modus operandi con su playbook, taxonomías, casos
    similares) se edita en vivo, sin versión ni borrador.
  - `OperationalSettings` es un singleton con efecto inmediato.
  - Por eso el agente **no escribe** en ninguno de los dos: sus cambios viven
    en el paquete candidato hasta que el usuario los aprueba (ver B1.2).
- Existen rollups de métricas de negocio y técnicas (`mark` vs `fraud_label`,
  tokens, latencia, fallos) y un LLM-judge muestreado (#22). Son insumos para
  metas y diagnóstico.
- No existe aún una función canónica de efectividad global, una plataforma de
  experimentos ni un agente conversacional.

## Principios de diseño

1. **Columna vertebral primero.** El orquestador, su estado persistido y el
   contrato de subagentes se construyen antes que los especialistas; los
   especialistas se enchufan después.
2. Los evaluadores deterministas verifican cada etapa y el resultado global. El
   agente nunca se verifica a sí mismo.
3. La efectividad global se calcula sobre el resultado final con una función
   objetivo versionada. No se promedian métricas incompatibles.
4. Los datos por caso permanecen en workers con acceso autorizado. El LLM
   recibe métricas agregadas y referencias opacas, nunca filas, payloads o
   documentos. El diagnóstico se apoya en agregados por segmento, etapa y ruta.
5. Todo candidato fija versiones, dataset, protocolo y presupuesto para que sus
   resultados sean reproducibles.
6. Experimentar y publicar son fases distintas. Aprobar y promover son
   acciones humanas, auditadas y ligadas al candidato evaluado.
7. Las decisiones del loop se basan en estado persistido (verificaciones,
   insights, decisiones), no en el historial conversacional del LLM.
8. Lo que el usuario dice en el chat es una **entrada**, no una orden
   privilegiada: puede orientar al agente, nunca ampliar sus límites duros ni
   su presupuesto.
9. La información que el usuario entrega al agente (texto, documentos,
   archivos) es contenido **no confiable** y su frontera de datos es distinta
   de la de los datos del sistema: el usuario la aporta de forma voluntaria,
   pero aun así se limita, se trata como dato (nunca como instrucción) y se
   somete a la política de retención y redacción acordada.
10. El agente **no modifica sus propios prompts, límites, presupuesto ni
    verificadores**. Esos cambios los hace una persona autorizada, con
    confirmación auditada, y cada ejecución registra qué versión de prompt
    usó.

## Fase 0 — Decisiones y criterios de éxito

### B0.1 — Definir la efectividad global
**Backend + negocio**

Acordar la etiqueta de éxito, el uso de `fraud_label`, la madurez de las
etiquetas, la métrica principal y las restricciones duras. Definir cobertura y
soporte mínimo por segmento.

**Decidido (2026-10-18):**
- **Etiqueta de éxito:** `fraud_label`, la realidad corregida por el equipo de
  fraude. Nunca `mark` (la decisión de ARIA, analista o voicebot).
- **Ventana de maduración del fraude:** una alerta cuenta para medir solo
  cuando pasa esa ventana, el momento en que ya se remarcó aproximadamente el
  9X % del fraude. Es una **entidad configurable**, no una constante (ver
  abajo).
- **Alertas inmaduras:** el monitoreo sí las muestra, marcadas como
  "madurando" como hoy. Ni el **reentrenamiento** ni el **agente** las usan,
  porque su `fraud_label` aún no es confiable: solo entran cuando pasan la
  ventana. Cada resultado del agente reporta su cobertura de alertas maduras y
  uno con poca cobertura no puede declarar ganador (B2.3).
- **Cuando se remarca**, el monitoreo la refleja como cerrada a nivel
  consolidado (los rollups ya aplican la corrección, −anterior/+nuevo); no
  hay que hacer nada nuevo para eso.
- **Métrica principal:** precisión y recall **por conteo**, no por monto,
  porque las reglas internas ya priorizan unas alertas sobre otras. Positivo =
  `fraud_label = fraud`; predicción positiva = `mark = fraud`; las alertas con
  `mark = pending` (bidi, escalamientos o voicebot sin resolver) quedan fuera.
  Los candidatos se ordenan **maximizando el recall con un piso de precisión
  configurable** (decidido 2026-10-18); el piso se fija en el menú de
  configuración del asistente y del optimizador. Los demás límites duros
  siguen en la decisión 2.

**Entidad "ventana de maduración del fraude".** Hoy la ventana está fija en
el código (`MATURING_DAYS = 4` y `MAY_VARY_MONTHS = 6` en `range_planner.py`) y
solo alimenta los avisos "madurando / puede variar / estable" de las métricas.
Se convierte en un dato configurable que leen tanto las métricas como el
optimizador:
- Tres consumidores, con reglas distintas: **monitoreo** (muestra todo, con
  aviso de madurez), **reentrenamiento** (solo datos maduros) y **agente**
  (solo datos maduros). Falta verificar dónde se arma el dataset de
  entrenamiento para aplicar el filtro de madurez ahí.
- Campos: `maturing_days` (la ventana), `expected_coverage_pct` (cuánto del
  fraude se espera ya remarcado en esa ventana; informativo, hoy ~98),
  `stable_months` (la cola larga, hoy 6) y el historial de cambios (quién y
  cuándo).
- Vive en `OperationalSettings`, igual que `amount_tiers`, y la modifican solo
  `release_manager` y `manager`. `range_planner` pasa a leerla en lugar de las
  constantes. Se edita desde el menú "Asistente y optimizador" de
  Configuración (ver "Configuración del asistente y del optimizador").
- El optimizador no la modifica. Al crear una sesión **copia su valor** dentro
  de la versión del objetivo (`agent_objectives`), de modo que los resultados
  siguen siendo reproducibles aunque la ventana cambie después.
- Para elegir el valor, el análisis de marcado de datasets ya calcula el
  perfil de maduración (promedio, mínimo, máximo, p95); se propone añadir más
  percentiles para ver en qué día se alcanza el porcentaje buscado.

**Aceptación:** función objetivo versionada, con ejemplos agregados y reglas
explícitas para casos sin etiqueta madura; la ventana es una entidad
configurable que usan las métricas y el optimizador.

### B0.2 — Política de experimentación, datos y presupuesto
**Backend + seguridad + negocio**

Datasets permitidos, particiones, segmentos, retención, límites de volumen y
presupuesto de cómputo. Definir cómo se **renueva** el presupuesto en un ciclo
prolongado (por sesión, por ventana de tiempo, por aprobación). Asignar roles
para crear, consultar, chatear, aprobar y promover.

**Aceptación:** política aplicable por backend; ningún límite depende de una
instrucción al LLM ni de lo dicho en el chat.

### B0.3 — Clasificar salidas y datos sensibles
**Backend + seguridad**

Revisar resultados por caso, informes, logs y errores para determinar qué
puede revelar datos. El detalle de corridas actual no es una frontera segura
para el agente.

**Aceptación:** contrato de salida segura aprobado, con campos permitidos y
excluidos.

### B0.4 — Alcance de control del agente
**Backend + negocio**

Inventariar cada entidad que gestiona el channel manager (configuración del
agente por paso, rúbricas, umbrales, watchlists, Biblioteca, Vector Stores,
modelos XGBoost; `OperationalSettings` y `AssistantOptimizerSettings` quedan
excluidas porque solo las modifican `release_manager` y `manager`) y declarar para cada una: qué puede
crear/modificar el agente, cómo se representa como borrador y cómo se aplica
al aprobarse.

**Aceptación:** tabla entidad → permisos del agente → representación candidata
→ flujo de aplicación existente.

## Fase 1 — Columna vertebral: sesiones, candidato y `verify`

### B1.1 — Sesión de optimización persistida
**Backend**

Una sesión de ciclo prolongado con objetivo y versión de métrica, alcance,
presupuesto vigente, estado, baseline, iteraciones, autor y marcas de tiempo.
Reutilizar ejecución asíncrona/Celery. Estados terminales y pausa explícita;
recuperable tras reinicios e idempotente ante reintentos. No persistir filas
del dataset.

**Aceptación:** sesión auditable que puede pausarse, reanudarse y cancelarse
sin perder evidencia.

### B1.2 — Paquete candidato versionado
**Backend**

Artefacto único que agrupa todo lo que el agente propone en una iteración:
versión candidata de configuración, entidades nuevas o modificadas de la
Biblioteca (incluidos modus operandi y sus playbooks), generación candidata de
Vector Store y modelo XGBoost candidato. Fija referencias exactas a dataset (hash/versión),
modelo, configuración, protocolo, particiones, parámetros y semilla.

Las entidades de la Biblioteca **no se escriben en sus tablas vivas**: residen en el paquete como borrador y se aplican por los flujos
existentes solo cuando el usuario aprueba.

**Aceptación:** el paquete muestra qué cambió y qué permaneció constante,
puede diferenciarse contra la versión activa y es inmutable una vez evaluado.

### B1.3 — Contrato seguro `verify`
**Backend**

Salida tipada con estado, métricas permitidas, intervalos o incertidumbre,
conteos protegidos por mínimos, versiones, regresiones, códigos de error
seguros y referencias opacas. Excluir filas, payloads, documentos, prompts,
razonamientos, errores crudos e identificadores sensibles.

**Aceptación:** el agente no puede acceder a datos sensibles por herramientas
alternativas ni obtenerlos mediante errores o logs.

### B1.4 — Autorización, auditoría y presupuestos
**Backend**

Roles en endpoints y casos de uso; auditoría de acciones y lecturas; límites de
candidatos, concurrencia, tiempo y coste impuestos en servidor. Evaluar si se
reutilizan los límites de pruebas o si el agente necesita presupuesto propio.

**Aceptación:** el agente no puede ampliar sus límites mediante argumentos de
herramienta ni mediante el chat; cada acción queda ligada a actor y sesión.

### B1.5 — API de sesiones y paquetes
**Backend + frontend API**

Crear, iniciar, pausar, reanudar, cancelar, consultar y listar sesiones,
iteraciones, paquetes y verificaciones seguras.

**Aceptación:** respuestas autorizadas y libres de datos por caso; idempotencia
y errores tipados documentados.

### B1.6 — Versionado de los prompts del agente
**Backend + seguridad**

Los prompts del orquestador, del chat, de los subagentes y de los
verificadores con LLM viven en un registro versionado e inmutable
(`agent_prompts`), con un puntero de versión activa auditado. Se siembra desde
archivos del repositorio, de modo que los valores por defecto pasan por
revisión de código, y se cambia en ejecución sin desplegar. Toda sesión fija
las versiones que usa al crearse, y cada run, mensaje del agente, llamada a
herramienta y paquete registra el `prompt_ref` usado.

El agente nunca edita sus propios prompts (principio 10). Decidido (17): los
gestionan los desarrolladores, sin interfaz de edición, y por ahora no se
evalúan antes de activarse. La activación y la reversión las hace el equipo de
desarrollo por un procedimiento operativo auditado.

**Aceptación:** dado un run, se reconstruyen el prompt exacto y sus variables;
activar o revertir una versión queda auditado; una sesión en curso no cambia
de prompt a mitad de camino.

## Fase 2 — Verificadores, metas y diagnóstico

### B2.1 — Evaluador global del pipeline
**Backend**

Calcular la función objetivo contra desenlaces maduros, con calidad, cobertura
y restricciones por segmento, número de casos etiquetados y ventana temporal.

**Aceptación:** resultados reproducibles para versiones fijadas; la marcación
del analista no se toma como verdad de terreno cuando el objetivo es fraude
real.

### B2.2 — Verificación por etapa y ruta
**Backend**

Integridad del flujo: saltos válidos, loops, fallos, escalamiento, duración y
coste; calidad solo con etiqueta apropiada. Diferenciar etapa omitida por ruta
válida de etapa fallida.

**Aceptación:** explica agregadamente las rutas recorridas sin exponer casos.

### B2.3 — Baseline y comparación estadística
**Backend**

Fijar corrida y versiones base; comparar candidatos bajo poblaciones y
protocolos equivalentes, con mínimos de muestra e incertidumbre.

**Aceptación:** no se declara ganador con muestra insuficiente o sin alcanzar
el criterio acordado.

### B2.4 — Proteger la partición final de evaluación
**Backend / training worker**

El loop no consulta repetidamente la partición final para escoger parámetros;
la evaluación final ocurre tras seleccionar el candidato.

**Aceptación:** se registra qué particiones se consultaron en cada iteración y
se reserva la evaluación final.

### B2.5 — Diagnóstico agregado
**Backend**

Herramienta de diagnóstico que responde "dónde y por qué falla" solo con
agregados: concentración de falsos positivos/negativos por segmento, canal,
subcanal, etapa y ruta; distribución de scores; discrepancias entre etapas;
señales del LLM-judge y de los rollups de #22. Los cortes por dimensión
respetan conteos mínimos.

**Aceptación:** el agente puede formular hipótesis específicas por segmento y
etapa sin acceder a un solo caso individual.

### B2.6 — Descubrimiento de patrones (modus operandi nuevos)
**Backend / worker autorizado**

Análisis ejecutado en un worker con acceso autorizado a datos (por ejemplo,
agrupar fraude no detectado o mal clasificado). Retorna al agente solo
descripciones agregadas de patrones, soporte y referencias opacas. El usuario
puede inspeccionar ejemplos por la UI con sus propios permisos; el agente no.

**Aceptación:** una propuesta de modus operandi nuevo incluye soporte
estadístico, evidencia agregada y referencias opacas verificables.

## Fase S — Muestreo de datos maduros

Decidido (2026-10-18): hace falta un componente nuevo, el **muestreador de
datasets**. Toma las alertas una vez cumplida la ventana de maduración, se
dispara según reglas estadísticas configurables y extrae una muestra de un
periodo configurable **anterior** a la ventana. Es la fuente de datos del
reentrenamiento y de la evaluación del agente: nada inmaduro entra. La ventana
es única, porque el comportamiento de maduración es casi indistinguible entre
canales.

**Ejemplo.** Ventana de 4 días, periodo de muestreo de 30 días y hoy 18 de
octubre. El periodo muestreado va del 14 de septiembre al 14 de octubre
(hoy − 4 días − 30 días, hasta hoy − 4 días). Una alerta del 16 de octubre no
entra: todavía no madura.

### BS.1 — Elegibilidad y filtro de madurez
**Backend**

Una alerta es elegible si su edad supera la ventana (medida igual que el
módulo de métricas, por la fecha de la alerta) y tiene `fraud_label` definida,
es decir `mark` distinto de `pending`. El filtro vive en el dominio, lo usan el
muestreador y el reentrenamiento, y lee la ventana de `OperationalSettings`.

**Aceptación:** ninguna alerta inmadura o `pending` aparece en una muestra;
cambiar la ventana cambia la elegibilidad de las muestras siguientes.

### BS.2 — Disparadores
**Backend**

Se puede activar cualquier combinación, evaluada con OR:
- **Periódico:** intervalo o cron en hora de Bogotá, con el Celery Beat del
  scheduler (#10). Por defecto, una vez por semana (decidido); los demás
  disparadores existen pero vienen apagados.
- **Por volumen:** al acumularse N alertas recién maduradas desde la última
  muestra.
- **Estadístico:** cuando la distribución de las recién maduradas se aparta de
  la de la última muestra más que un umbral configurable (tasa de fraude, mezcla
  por canal, subcanal y tramo de monto). La prueba concreta la elige el
  equipo de desarrollo (por ejemplo, un índice de estabilidad de población).
- **Manual:** desde la interfaz, para quien tenga permiso.

Un enfriamiento mínimo evita disparos seguidos, y todo disparo es idempotente
por periodo y especificación. Una tarea periódica evalúa los disparadores con
los contadores de `dataset_sampler_state`.

**Aceptación:** dos evaluaciones del mismo periodo no generan dos muestras;
cada disparo registra qué regla lo activó.

### BS.3 — Muestreo estadístico configurable
**Backend**

Parámetros: duración del periodo en días, tamaño (fijo, o calculado desde un
margen de error y un nivel de confianza), estratificación (`fraud_label`,
canal, subcanal, tramo de monto), mínimo por estrato, sobremuestreo de la
clase fraude o razón objetivo, semilla, y versiones de esquema de alerta
compatibles (el esquema está versionado y una muestra no debe mezclar
versiones incompatibles). La lectura usa el índice por día de creación de
`alerts` (`CreatedDayIdx`), nunca `Scan`.

**Aceptación:** misma especificación, mismo periodo y misma semilla producen la
misma muestra.

### BS.4 — Particiones
**Backend**

Cada alerta de la muestra se asigna a entrenamiento, validación, prueba o
final por un hash determinista de su identificador, con proporciones
configurables. La partición final queda reservada (B2.4).

**Aceptación:** la asignación es estable entre ejecuciones; la partición final
no se consulta para escoger parámetros.

### BS.5 — Muestra inmutable (snapshot)
**Backend**

Cada ejecución produce un registro inmutable en `dataset_snapshots` con la
especificación usada (copia), el periodo, la ventana vigente, los conteos por
estrato y partición, la versión de esquema, el hash del contenido y el
disparador. El contenido se materializa en el catálogo de datasets existente
(un dataset por partición); esto debe verificarse contra el flujo de
entrenamiento actual antes de darlo por válido. El agente solo recibe la
referencia opaca y los conteos agregados; las filas se quedan en el worker.

**Aceptación:** una muestra no se modifica una vez creada; el entrenamiento y
el evaluador consumen la misma referencia.

### BS.6 — Ejecución
**Backend**

Tarea Celery en un worker con acceso autorizado, con seguimiento en
`async_operations`, límite de volumen leído por ejecución y reintentos
idempotentes. Retiene un número máximo de muestras configurable; las demás se
archivan o se borran según la política de retención.

### BS.7 — Consumidores
**Backend**

El reentrenamiento de modelos y los verificadores del agente leen únicamente
muestras de `dataset_snapshots`. Las pruebas del pipeline pueden usarlas
también. El monitoreo no depende de ellas.

### BS.8 — Vista previa del muestreo
**Backend + frontend**

Dada la especificación actual, devuelve solo agregados: alertas elegibles,
conteo por estrato, tamaño estimado de la muestra y qué disparadores se
activarían hoy. La usa el menú de configuración para validar un cambio antes de
guardarlo.

**Aceptación:** la vista previa nunca devuelve filas ni identificadores.

## Fase 3 — Orquestador y contrato de subagentes

### B3.1 — Contrato de subagente
**Backend**

Interfaz común para especialistas: entrada (alcance, hipótesis, presupuesto
asignado), salida (contribución al paquete candidato + resultado `verify`),
límites y cancelación. Los especialistas se registran por área sin cambiar el
orquestador.

**Aceptación:** un subagente de prueba (stub) se enchufa y ejecuta de extremo a
extremo sin tocar el orquestador.

### B3.2 — Orquestador
**Backend**

Ciclo persistido y prolongado:
1. leer verificaciones, diagnóstico e insights activos;
2. formular hipótesis y priorizarlas;
3. escoger subagente(s) dentro del alcance;
4. construir/actualizar el paquete candidato;
5. verificar con los evaluadores deterministas;
6. actualizar ranking y registrar la decisión con su evidencia;
7. repetir mientras haya señal y presupuesto.

Para por meta cumplida, presupuesto agotado, regresión de límites duros, falta
de señal o instrucción del usuario. Al parar, deja un paquete recomendado con
su evidencia.

**Aceptación:** cada decisión referencia evidencia; recuperación tras fallo e
idempotencia; criterios de parada deterministas.

### B3.3 — Combinaciones
**Backend**

Primero medir cambios aislados; con evidencia, evaluar combinaciones de
versiones exactas de modelo, configuración, Biblioteca y/o Vector Store de
extremo a extremo. La combinación se rechaza si rompe restricciones globales.

## Fase 4 — Chat e insights

### B4.1 — Chat con el orquestador
**Backend + frontend**

Canal conversacional por sesión, restringido a roles autorizados. El contexto
del modelo se arma desde estado persistido (resumen versionado de la sesión,
insights activos, decisiones recientes, estado del loop), no desde el
historial completo. El chat puede consultar el estado, pedir explicaciones,
pausar o reanudar, reordenar prioridades y acotar el alcance. No puede ampliar
límites duros, presupuesto ni permisos.

**Aceptación:** una conversación larga no degrada el contexto; el chat nunca
revela datos por caso.

### B4.2 — Modelo de insights
**Backend**

Un insight es una afirmación del usuario (o del propio agente) que se
convierte en estado estructurado y consultable:

- `kind`: observación, hipótesis, restricción, preferencia, directiva,
  pregunta, decisión.
- Contenido, alcance (segmento, canal, entidad), autor y rol, mensaje de
  origen, marcas de tiempo, confianza declarada.
- `status`: propuesto → confirmado → activo → aplicado / refutado /
  reemplazado / rechazado / vencido.
- Vínculos: hipótesis que genera, candidatos que lo ejercen, verificaciones
  que lo validan o refutan, insight que reemplaza.

**Aceptación:** cada insight activo es recuperable por alcance y tiene
trazabilidad completa hasta el efecto que produjo.

### B4.3 — Extracción y confirmación
**Backend**

El agente propone insights extraídos de la conversación y **los devuelve al
usuario para confirmar** ("entendí X, alcance Y") antes de usarlos como
preferencias, restricciones o instrucciones activas. Los hallazgos estadísticos
derivados de datos elegibles siguen el ciclo de evidencia de B2.5/B2.6 y no
requieren confirmación caso por caso ni confirmación humana para guardarse.
Las restricciones se validan contra los límites duros; si chocan, se explica y
no se aplican.

**Aceptación:** ninguna instrucción conversacional no confirmada afecta al loop;
los hallazgos de datos se identifican como evidencia del optimizador, con su
procedencia, y nunca como decisiones humanas.

### B4.4 — Cierre del ciclo insight → evidencia
**Backend**

Cada insight activo se traduce en hipótesis comprobables. El resultado
verificado se vincula de vuelta: validado, refutado o no concluyente. Si la
evidencia contradice al usuario, el agente lo dice con datos y no obedece en
silencio. Un insight no verificable se conserva como preferencia.

**Aceptación:** el usuario ve qué hizo el agente con cada insight y con qué
resultado.

### B4.5 — Memoria de sesión y de largo plazo
**Backend**

Resumen versionado de cada sesión (decisiones, aprendizajes, pendientes).
Los hallazgos agregados respaldados por datos se guardan en `optimizer_insights`
y se recuperan para sesiones futuras por segmento. Cada sesión los reevalúa con
la nueva muestra y puede mantenerlos, refutarlos o marcarlos obsoletos. Las
propuestas conversacionales de `agent_insights` no se arrastran como
instrucciones sin confirmación explícita. La evidencia de casos elegibles puede
respaldar un hallazgo sin confirmación humana individual; persistirlo no lo
aprueba ni autoriza cambios en producción.

### B4.6 — Entrada no confiable
**Backend + seguridad**

El texto del chat y cualquier contenido que cite se tratan como datos, no
como instrucciones del sistema. Pruebas de inyección: un mensaje no puede
alterar límites, roles, presupuesto ni activar acciones de aprobación.

## Fase A — Modo asistente (primer vertical)

Depende de B1.1–B1.5 (sesión, paquete, autorización), B3.1 (contrato de
subagente) y B4.1–B4.3 (chat e insights). Se construye antes que la
optimización.

### BM.1 — Entrada del usuario y política de datos
**Backend + seguridad**

Decidido (2026-10-18): en la v1 el usuario entrega **solo texto pegado** en el
chat; no hay archivos adjuntos. Los adjuntos (`agent_attachments`) quedan
fuera de la v1. El texto se pasa al modelo como dato delimitado, nunca como
instrucción.

**Enmascarado de datos personales (decidido 2026-10-18).** Los datos
personales del texto no aportan nada: lo que sirve es el modus operandi
inferido. Por eso:
- Un puerto `PersonalDataMasker` (ABC con un método, adaptador de
  infraestructura basado en reglas) se aplica en el borde, **antes** de
  persistir el mensaje y antes de llamar al modelo. El original no se guarda
  en ninguna parte: el enmascarado es irreversible.
- Reemplaza por marcadores (`[PERSONA_1]`, `[CC_1]`, `[TEL_1]`, `[CUENTA_1]`,
  `[TARJETA_1]`, `[EMAIL_1]`, `[IP_1]`…), consistentes dentro de un mismo
  mensaje. Se conserva el patrón descrito y los importes.
- Ante la duda se enmascara de más: perder un dato es aceptable; dejar pasar
  uno no.
- En `agent_messages` solo se guarda cuántos datos de cada tipo se
  enmascararon, nunca los valores.
- Se aplica también a lo que escribe el agente y al borrador (BM.3): una
  entrada de la Biblioteca no puede contener datos personales.
- Los nombres propios son el caso difícil y pueden escaparse; se cubren con
  heurísticas y se prueban con formatos colombianos reales (cédula, NIT,
  celular, cuentas, tarjetas).
- No se usa KMS para esto; el cifrado en reposo de las tablas es un tema de
  plataforma, aparte.

**Aceptación:** política aplicada por backend; un adjunto no puede alterar
límites, roles ni acciones (B4.6 aplica también aquí).

### BM.2 — Subagente generador de entidades
**Backend**

Recibe la información del usuario y el tipo de entidad pedido, y produce un
borrador completo. Cubre **toda la Biblioteca** (modus operandi con su
playbook, taxonomías, casos similares, watchlists, flags y el resto de
entradas), tanto para **crear** como para **editar** (y proponer eliminar) una
entrada existente. Para una edición parte de la entrada viva y muestra el
diff. Se entrega por tipo, empezando por modus operandi (método principal más
`if_no_voicebot` / `if_no_analyst`), porque cada tipo necesita su verificador
(BM.3). Pregunta por lo que falta en lugar de
inventarlo, e indica la procedencia de cada campo: tomado de lo entregado por
el usuario o inferido por el agente.

Decidido (2026-10-18): el asistente también puede editar la **configuración
del agente** (rúbricas, prompts de la configuración, umbrales, reglas), no solo
la Biblioteca. Una edición de configuración produce una versión candidata
nueva e inactiva y se activa por el flujo de solicitudes de despliegue
existente, con confirmación. El asistente también puede trabajar con **Vector Stores** (construir una
generación candidata) y **modelos XGBoost** (entrenar un candidato), con las
mismas reglas de confirmación (decisión 18). En ambos casos construir y
activar son acciones separadas: entrenar un modelo o construir una generación
es una confirmación; activar el modelo o promover el Vector Store a producción
es otra, sobre el resultado ya verificado. El asistente **no** toca
`OperationalSettings` (solo `release_manager` y `manager`). El asistente también puede
proponer lanzar un optimizador; el inicio siempre lo confirma el usuario.

**Aceptación:** el borrador marca qué campos son inferidos; ningún campo
obligatorio se completa sin fuente o sin confirmación del usuario.

### BM.3 — Verificadores ligeros y deterministas
**Backend**

Revisan el borrador antes de mostrarlo:
- validación de esquema y de campos obligatorios;
- detección de duplicados o solapes con entidades existentes mediante la
  búsqueda del Vector Store;
- existencia y coherencia de la taxonomía padre;
- coherencia de los fallbacks del playbook;
- ausencia de datos personales en el borrador (el mismo enmascarador se aplica
  a la salida y cualquier hallazgo bloquea);
- opcional: correr el borrador contra alertas de prueba y reportar agregados.

Cada tipo de entidad de la Biblioteca define su propio conjunto de
verificadores (esquema, duplicados, referencias, coherencia). Para ediciones
se añade: diff contra la entrada viva y control de `base_version`, que avisa
si la entrada cambió desde que se creó el borrador.

Para Vector Stores y modelos XGBoost los verificadores sobre el candidato son:
- Vector Store: integridad de la generación construida, que los documentos
  esperados estén y la calidad de recuperación con consultas autorizadas,
  devuelta como agregados.
- Modelo: que el informe de entrenamiento esté completo (particiones, métricas
  por umbral, hash del dataset), que no se haya consultado la partición final
  para escoger parámetros (B2.4) y comparación con el modelo activo.

**Aceptación:** el resultado de cada verificador se muestra junto al borrador;
un fallo bloquea la aprobación hasta corregirlo o aceptarlo de forma explícita
y auditada.

### BM.4 — Borrador y aprobación
**Backend**

Paquete candidato liviano de una o varias entradas de la Biblioteca (crear,
editar o eliminar). El usuario puede editarlo por
chat o directamente. Al aprobarse, se aplica con el caso de uso de creación ya
existente (incluido el cálculo de embedding) y queda auditado con autor,
aprobador y adjuntos de origen. Mientras no se apruebe, nada se escribe en la
Biblioteca.

**Aceptación:** el agente no crea entidades vivas; la aprobación queda ligada
al borrador exacto verificado.

### BM.5 — Roles
**Backend + negocio**

Definir qué roles pueden usar el modo asistente, qué tipos de entidad puede
pedir cada rol y quién aprueba. La creación por asistente no debe dar más
permisos que la creación manual del mismo rol.

### BM.6 — Pruebas de fuga e inyección
**Backend + seguridad**

Adjuntos con valores señuelo e instrucciones maliciosas: verificar que no
aparecen en trazas, logs ni resúmenes de sesión, y que no alteran el
comportamiento del agente ni los verificadores.

### BM.7 — Confirmación obligatoria y auditoría
**Backend + seguridad**

Decidido (2026-10-18): el agente **siempre pide confirmación** antes de
cualquier escritura sobre una entidad viva, y esa confirmación se guarda como
auditoría. Aplica a crear, editar y eliminar, y también al modo optimización.

- La confirmación es una acción explícita en la interfaz, sobre el borrador y
  el diff exactos que el usuario ve. Un "sí" escrito en el chat **no** la
  sustituye (evita ambigüedad e inyección).
- Se registra en `agent_confirmations`: quién y con qué rol, cuándo, qué
  acción, sobre qué ítem, el hash del contenido y del diff mostrados, la
  `base_version`, el estado de los verificadores en ese momento y el mensaje
  de origen. El registro es append-only: no se actualiza ni se borra.
- Se vincula a la auditoría de infraestructura (`AuditPort`) y al evento de
  aplicación de la entidad.
- La confirmación pierde validez si cambia el borrador (el hash ya no
  coincide) o la entidad viva (`base_version`): se pide de nuevo.
- Al aplicar, el caso de uso verifica que exista una confirmación válida para
  ese hash; sin ella la aplicación falla.

**Aceptación:** ningún cambio llega a una entidad viva sin una confirmación
registrada y vigente; la confirmación puede reconstruirse completa desde la
auditoría.

### BM.8 — Coordinación con el optimizador y aviso de interferencia
**Backend**

Cuando una sesión de optimización está activa sobre un alcance, el asistente
(y cualquier editor) debe poder saberlo. El backend expone, por entidad o área,
qué sesiones de optimización la reclaman (`agent_entity_claims`) y desde
cuándo, y el asistente lo incluye en su respuesta y en el borrador. El aviso es
informativo: no bloquea. Al confirmar se vuelve a comprobar `base_version`,
y si la entidad cambió, la confirmación se invalida (BM.7).

**Aceptación:** abrir o editar una entidad dentro del alcance de un optimizador
activo devuelve el aviso con sesión, alcance y marca de tiempo; un cambio hecho
durante la sesión queda registrado en ella y marca como obsoletos los ítems
afectados.

### FM.1 — Interfaz del asistente
**Frontend**

Panel lateral derecho superpuesto, disponible en Configuración, Testing,
Biblioteca y Modelos (ver "Planificación de frontend"): conversar con el asistente, ver el borrador con la procedencia de cada campo y los
resultados de los verificadores, editar, aprobar o descartar.

**Aceptación:** el usuario ve qué viene de su información y qué infirió el
agente antes de aprobar; solo se ofrecen tipos de entidad autorizados.

## Fase 5 — Subagentes por área

Cada uno cumple B3.1 y aporta al paquete candidato (B1.2).

### B5.1 — Configuración del agente
Rúbricas, prompts, herramientas por paso, umbrales y reglas determinísticas,
usando preview y versionado existentes. Pruebas contra una versión fijada.

### B5.2 — Biblioteca y entidades nuevas
Crear y modificar modus operandi (con playbook y fallbacks), taxonomías, casos
similares y watchlists como borradores del paquete. Parte de B2.6 para
proponer entidades nuevas con evidencia.

### B5.3 — Vector Store
Construir una generación candidata desde el manifiesto versionado, validar
integridad y calidad de recuperación con consultas autorizadas, devolver
agregados seguros.

### B5.4 — Modelo XGBoost
Candidatos nuevos sobre un dataset autorizado, parámetros dentro de rangos
aprobados, reporte y protocolo registrados. El modelo activo nunca se
modifica.

### B5.5 — Operación (descartado)
`OperationalSettings` solo lo modifican `release_manager` y `manager`, y el
optimizador solo lo lanza `channel_manager`. El agente no lo toca ni lo
propone en un paquete. Si en el futuro se quiere que sugiera ajustes de
capacidad, sería un informe de texto para esos roles, fuera del paquete.

## Fase 6 — Interfaz de usuario

> La ubicación y estructura de la interfaz (panel lateral derecho, pestañas
> por conversación, optimizador sin pantalla propia) están en "Planificación de
> frontend". Esta fase lista las capacidades; algunas se leen como pestañas o
> vistas del panel, no como rutas.

### F6.1 — Centro del orquestador
Definir objetivo, dataset autorizado, alcance, presupuesto y restricciones;
explicar qué puede modificar el agente y qué se evaluará.

### F6.2 — Chat y panel de insights
Chat junto al estado del loop. Panel de insights con estado, vínculos y
resultado; confirmar, editar o rechazar los propuestos por el agente.

### F6.3 — Progreso del loop
Hipótesis resumida, subagente elegido, estado de verificación, coste
acumulado, motivo de parada y presupuesto restante.

### F6.4 — Comparar baseline y paquetes
Métrica global, restricciones, resultados por área y segmento, incertidumbre,
cobertura de etiquetas, diffs de cada entidad. Candidatos rechazados y su
motivo.

### F6.5 — Revisar y aprobar
Diffs y evidencia `verify` por ítem; aprobación por ítem o por paquete que
dispara los flujos existentes de activación/promoción según rol.

**Aceptación:** el loop no publica; aprobación y promoción quedan auditadas y
ligadas al paquete evaluado.

### F6.6 — Cliente API, estados y permisos
Tipos, polling de progreso, errores seguros y controles según permisos. El
backend sigue siendo autoridad de acceso.

## Fase 7 — Operación y seguridad

### B7.1 — Observabilidad y auditoría del agente
Sesión, iteración, subagente, herramienta, duración, coste y estado con
atributos de baja cardinalidad, bajo el contrato OTLP existente. Sin datos
sensibles en spans ni métricas.

### B7.2 — Pruebas de fuga de datos
Valores señuelo en datasets, payloads, errores y mensajes de chat; verificar
que no aparecen en respuestas, trazas, logs, resúmenes de sesión ni insights.

### B7.3 — Kill switch, cancelación y recuperación
Detener iteraciones, cancelar trabajos y recuperar estados sin borrar
evidencia de auditoría. Un ciclo prolongado exige además detección de
estancamiento y de coste anómalo.

### F7.4 — Herramientas operativas en UI
Cancelación, límites alcanzados, fallos seguros, historial y autor/aprobador.

## Fase 8 — Validación y salida gradual

### X8.1 — Evaluación retrospectiva
Dataset autorizado con baseline fijo, desenlaces maduros y partición final
reservada. **Aceptación:** mejora defendible sin violar límites globales ni por
segmento.

### X8.2 — Shadow mode
Ejecutar recomendaciones sin influir en decisiones productivas; comparar
candidato y sistema vigente, observando deriva y coste.

### X8.3 — Promoción gradual y rollback
Aprobación humana, despliegue gradual y reversión ante umbrales de degradación
definidos.

## Modelo de datos y runtime

Propuesta de diseño, alineada con los patrones del repo: una tabla DynamoDB
por agregado con constante `*_TABLE` en `schemas.py`, un puerto
autocontenido por entidad (dataclass + enum + Protocol en un solo archivo) y
un repositorio `Dynamo*Repository`. Nada de `Scan`: toda consulta tiene clave
o GSI. Las tablas nuevas deben entrar también en `manager.py`, el catálogo de
respaldos, el `e2e_state_cleaner` y el aprovisionamiento de OKD (hoy pendiente
para las tablas de #22).

### Mapa de relaciones

```
agent_objectives (versionado) ──┐
                                ▼
agent_sessions ──< agent_iterations ──< agent_runs ──< agent_tool_calls
   │  │  │               │                  │
   │  │  │               │                  └── async_operations (1:1, existente)
   │  │  │               ├──> agent_hypotheses ◄── agent_findings (diagnóstico)
   │  │  │               ├──> agent_packages ──< items ──> entidades vivas*
   │  │  │               └──> agent_verifications (sobre paquetes/runs)
   │  │  └──< agent_budget_ledger
   │  └──< agent_session_summaries
   └──< agent_messages ──< agent_attachments (contenido en object storage)
              │
              └─ extrae ─> agent_insights ──(agent_links)──> hipótesis,
                                                              paquetes, verificaciones
* solo se escriben al aprobar y vía los casos de uso existentes
```

### Tablas

Convención de claves: `pk`/`sk` como `metrics_rollups`; `rev` entero para
control de concurrencia optimista (escritura condicional); `expires_at` para
retención; identificadores UUID o ULID; sin datos por caso en ningún atributo.

#### Núcleo del orquestador

**`agent_sessions`** — una sesión por conversación/ciclo, en ambos modos.
- Clave: `session_id`.
- Atributos: `mode` (`assistant` | `optimization`), `status`, `title`,
  `created_by`/`created_by_id`, `created_at`/`updated_at`, `objective_id` +
  `objective_version`, `scope` (áreas y entidades habilitadas),
  `budget_limits` (copia congelada de la política al crear), `budget_spent`
  (contadores atómicos), `baseline_ref`, `current_package_id`,
  `final_partition_reserved`, `stop_reason`, `summary_version`,
  `prompt_versions` (versiones de prompt fijadas al crear la sesión),
  `lease_owner`/`lease_expires_at`, `rev`.
- GSIs: `OwnerIdx` (`created_by_id`, `created_at`) para "mis sesiones";
  `StatusIdx` (`status`, `updated_at`) para recuperación y kill switch.
- Estados: `DRAFT → ACTIVE ⇄ PAUSED`, `ACTIVE → WAITING_USER` (pregunta o
  confirmación pendiente), `ACTIVE → WAITING_APPROVAL` (paquete recomendado),
  terminales `COMPLETED`, `STOPPED` (meta, presupuesto, regresión o falta de
  señal), `CANCELLED`, `FAILED`. En modo asistente el ciclo es
  `ACTIVE → WAITING_USER → WAITING_APPROVAL → COMPLETED`.

**`agent_iterations`** — una vuelta del ciclo; en modo asistente hay una o
pocas.
- Clave: `session_id` + `n` (entero con relleno de ceros).
- Atributos: `status`, `hypothesis_ids`, `run_ids`, `package_id`,
  `verification_ids`, `partitions_consulted`, `decision`
  (`{action, rationale, evidence_refs}`: es el registro de decisiones,
  principio 7), `budget_delta`, `started_at`/`finished_at`.
- La iteración `n` solo se crea con escritura condicional si la `n-1` está
  cerrada: idempotencia ante reintentos del orquestador.

**`agent_hypotheses`**
- Clave: `session_id` + `hypothesis_id`.
- Atributos: `statement`, `area` (tipo de subagente), `derived_from` (insights
  y hallazgos, por id), `priority`, `expected_effect` (métrica esperada),
  `status` (`PROPOSED`, `QUEUED`, `TESTING`, `VALIDATED`, `REFUTED`,
  `INCONCLUSIVE`, `ABANDONED`), `iteration_id`, `result_verification_ids`.

**`agent_findings`** — salida del diagnóstico agregado (B2.5) y del
descubrimiento de patrones (B2.6).
- Clave: `session_id` + `finding_id`.
- Atributos: `kind`, dimensión (segmento, canal, subcanal, etapa, ruta),
  métricas agregadas con su conteo (nunca por debajo del mínimo acordado),
  periodo, `source` (rollups #22, judge, entrenamiento), `opaque_refs`.

**`optimizer_insights`** — hallazgos agregados que pueden retomarse entre
sesiones. Es distinto de `agent_insights`, que representa afirmaciones o
propuestas conversacionales ligadas a una sesión.
- Clave: `insight_id` (global, estable).
- Atributos: `statement`, `kind` (`PATTERN`, `HYPOTHESIS`), `scope_key`
  (segmento estable), `status` (`SUPPORTED`, `REFUTED`, `STALE`, `RETIRED`),
  `evidence_summary` (métricas agregadas y `sample_count`), periodo observado,
  `dataset_snapshot_ids`, `finding_ids`, versión de esquema y mapping de
  etiquetas, `origin_session_id`/`origin_run_id`, `created_at`,
  `last_evaluated_at`, `review_after`, `supersedes_id`, `rev`.
- Índices: `ScopeStatusIdx` (`scope_key`, `status`) para recuperar el contexto
  de una sesión por segmento; `StatusReviewIdx` (`status`, `review_after`) para
  localizar hallazgos que deben reevaluarse.
- Solo persiste evidencia agregada y referencias opacas a snapshots/findings;
  no guarda filas, identificadores ni datos personales de alertas. Solo se
  publica cuando el segmento tiene al menos 30 casos. Ese umbral permite
  mostrar el agregado, pero por sí solo no declara estadísticamente válido el
  patrón.
- Al abrir una sesión, se cargan hallazgos `SUPPORTED` del mismo segmento como
  contexto etiquetado “respaldado por datos”, junto con su muestra y periodo.
  No equivalen a una confirmación humana, no ejecutan acciones y se vuelven a
  evaluar con la muestra nueva. Si la evidencia contradice el patrón, se
  registra `REFUTED`; si sus datos/versiones ya no son comparables, `STALE`.

#### Runtime: subagentes y ejecución

**`agent_runs`** — ejecución de un subagente (o de un paso del orquestador)
sobre Celery.
- Clave: `session_id` + `run_id`.
- Atributos: `iteration_id`, `subagent_kind`, `contract_version`,
  `input_ref` (opaco), `status`, `operation_id` (enlace 1:1 a
  `async_operations`, que sigue siendo la fuente del despacho y del polling
  genérico), `queue`, `attempt`/`max_attempts`, `heartbeat_at`,
  `lease_expires_at`, `budget_allocated`, `budget_spent`
  (`tokens`, `usd`, `seconds`, `candidates`), `output_ref`, `verify_ids`,
  `error_code` (seguro, nunca el error crudo), `cancel_requested`, `rev`.
- GSI: `StatusLeaseIdx` (`status`, `lease_expires_at`) para que un barrido
  detecte runs `RUNNING` con lease vencido y los reintente o cierre.
- Estados: `PENDING → DISPATCHED → RUNNING → SUCCEEDED | FAILED | CANCELLED
  | TIMED_OUT`.

**`agent_tool_calls`** — medición y auditoría de cada herramienta que usa un
run.
- Clave: `run_id` + `seq`.
- Atributos: `tool`, `args_hash` (no los argumentos crudos), `status`,
  `duration_ms`, `tokens`, `cost`, `safe_result_ref`, `created_at`,
  `expires_at`. Alimenta el gasto de presupuesto y las pruebas de fuga.

#### Conversación e insights

**`agent_messages`**
- Clave: `session_id` + `seq` (entero creciente por sesión).
- Atributos: `message_id`, `client_message_id` (idempotencia de reintentos del
  navegador, con escritura condicional), `role` (`user` | `agent` | `system`),
  `content` (texto ya enmascarado, hasta `assistant_max_message_chars`, 8.000 por
  defecto; sin `content_ref` ni adjuntos en la v1), `author_id`, `run_id` (qué
  ejecución respondió), `extracted_insight_ids`, `redaction` (cuántos datos de
  cada tipo se enmascararon, nunca los valores), `tokens`, `created_at`,
  `expires_at`.
- El frontend lee por `after_seq`; el contexto del modelo no usa estos
  mensajes completos (B4.1).
- **Dimensionamiento.** Cada mensaje es un ítem propio, no un elemento de una
  lista dentro de la sesión, así que ningún ítem crece con la conversación. Un
  mensaje de 8.000 caracteres pesa unos 9 KB (el español lleva tildes de 2
  bytes), unas 45 veces menos que el límite de 400 KB por ítem de DynamoDB. En
  el peor caso planteado, 1.000 mensajes diarios al tope serían unos 9 MB al
  día y unos 6,5 GB en dos años. Con el volumen esperado ("no serán muchos")
  es mucho menos.
- **Topes impuestos en el servidor:** tamaño por mensaje (se rechaza con error
  tipado que pide dividirlo), mensajes por sesión, ritmo de mensajes por
  usuario y página máxima de lectura (50 mensajes por consulta, muy por debajo
  del 1 MB que devuelve una consulta de DynamoDB). El agente limita su propia
  salida con `max_output_tokens` en el prompt, de modo que sus mensajes caben
  en el mismo tope. El tope existe sobre todo por el contexto y el coste del
  modelo, no por DynamoDB.

**`agent_attachments`**
- Clave: `session_id` + `attachment_id`.
- Atributos: `filename`, `mime`, `size`, `sha256`, `storage_ref` (contenido en
  el object storage existente, nunca en DynamoDB), `status` (`UPLOADED`,
  `SCANNING`, `READY`, `QUARANTINED`, `DELETED`), `pii_flags`, `uploaded_by`,
  `expires_at`.

**`agent_insights`**
- Clave: `session_id` + `insight_id`.
- Atributos: `kind` (`observation`, `hypothesis`, `constraint`, `preference`,
  `directive`, `question`, `decision`), `statement`, `scope`
  (`{type, ref}`, p. ej. segmento o entidad), `status` (`PROPOSED`,
  `CONFIRMED`, `ACTIVE`, `APPLIED`, `REFUTED`, `SUPERSEDED`, `REJECTED`,
  `EXPIRED`), `proposed_by` (`user` | `agent`), `confidence`,
  `source_message_id`, `confirmed_by`/`confirmed_at`, `supersedes_id`,
  `carry_over` (si pasa a otras sesiones, B4.5), `expires_at`, `rev`.
- GSIs: `ScopeStatusIdx` (`scope_key`, `status`) para traer los insights
  activos de un alcance; `CarryOverIdx` (`carry_over_owner`, `created_at`),
  índice disperso que solo contiene insights activos con `carry_over`.

**`agent_links`** — aristas del grafo insight → hipótesis → paquete →
verificación (B4.4).
- Clave: `session_id` + `sk` = `src_type#src_id#rel#dst_type#dst_id`.
- Atributos: `rel` (`generates`, `exercised_by`, `validated_by`,
  `refuted_by`, `supersedes`), `created_at`.
- GSI: `DstIdx` (`dst_key`, `src_key`) para el camino inverso ("¿qué insights
  respaldan este cambio?").

**`agent_session_summaries`**
- Clave: `session_id` + `version`.
- Atributos: resumen estructurado (decisiones, aprendizajes, pendientes),
  `covers_seq_from`/`covers_seq_to`, `created_at`. Inmutables; el contexto del
  chat toma la última versión.

#### Evidencia y metas

**`agent_objectives`** — función objetivo versionada (B0.1).
- Clave: `objective_id` + `version`.
- Atributos: etiqueta de éxito (`fraud_label`), ventana de maduración (valor copiado de la
  entidad, no una referencia viva), métricas principales (precisión y recall
  por conteo),
  restricciones duras, soporte mínimo por segmento, regla para casos sin
  etiqueta madura, `status` (`DRAFT`, `ACTIVE`, `RETIRED`), `created_by`,
  `approved_by`. Inmutable una vez activa.

**`agent_verifications`** — contrato `verify` (B1.3).
- Clave: `subject_id` (paquete o run) + `sk` = `verifier#seq`.
- Atributos: `verifier` (`global_effectiveness`, `stage_route`, `schema`,
  `duplicates`, `taxonomy`, `playbook_fallbacks`, `dry_run`, `leakage`),
  `status`, métricas permitidas, incertidumbre, conteos protegidos,
  regresiones, `objective_version`, versiones evaluadas, `protocol`,
  `partitions_consulted`, `error_code`, `opaque_refs`, `run_id`, `created_at`.

#### Salida: paquete candidato

**`agent_packages`**
- Clave: `package_id` + `sk` (`meta` | `item#<item_id>`).
- GSI: `SessionIdx` (`session_id`, `created_at`).
- `meta`: `session_id`, `iteration_id`, `parent_package_id`, `status`
  (`DRAFT`, `EVALUATING`, `SEALED`, `RECOMMENDED`, `APPROVED`,
  `PARTIALLY_APPLIED`, `APPLIED`, `REJECTED`, `SUPERSEDED`), `content_hash` y
  `sealed_at` (tras sellar es inmutable), refs de baseline, dataset (hash),
  protocolo, particiones y semilla, `recommended_at`, `rev`.
- `item#…`: `item_type` (`configuration_version`, `library_modus_operandi`,
  `library_taxonomy`, `library_similar_case`, `library_watchlist`,
  `library_flag` y el resto de entradas de la Biblioteca,
  `vector_store_generation`, `model_candidate`), `operation` (`create` | `update` |
  `delete`), `target_ref`, `base_version` (para detectar que la entidad viva
  cambió desde que se creó el borrador), `draft` (en línea si es pequeño; si
  no, `draft_ref`), `field_provenance` (por campo: `user_input` | `inferred` |
  `agent_generated`, con el adjunto o mensaje de origen), `verification_status`,
  `approval_status` (`PENDING`, `APPROVED`, `REJECTED`, `APPLIED`,
  `APPLY_FAILED`), `approved_by`/`approved_at`, `applied_ref`.
- Al aprobar un ítem se aplica con el caso de uso existente de su entidad. Para
  `configuration_version` se reutiliza el flujo de solicitudes de despliegue
  (`configuration_deploy_requests`), no una vía paralela.

#### Presupuesto

**`agent_budget_ledger`**
- Clave: `session_id` + `ts#entry_id`.
- Atributos: `entry_type` (`ALLOCATE`, `SPEND`, `RENEW`, `DENY`), montos por
  recurso, `actor`, `reason`. Cada ampliación requiere aprobación explícita
  del `channel_manager` y se registra como `RENEW`; la sesión pausada continúa
  solo tras esa autorización. El tope se impone con una escritura condicional sobre
  `agent_sessions.budget_spent` (gasto + delta ≤ límite), no con una
  instrucción al LLM.

#### Configuración y muestreo

**`assistant_optimizer_settings`** — singleton (clave fija `current`) con los
campos de "Configuración del asistente y del optimizador", más `rev`.
**`assistant_optimizer_settings_changes`**: historial append-only
(`settings`, `ts#change_id`) con autor, hora y diff.

**`dataset_snapshots`** — muestra inmutable del muestreador (BS.5).
- Clave: `snapshot_id`. GSI `CreatedIdx` (`kind`, `created_at`) para listar y
  retener.
- Atributos: `trigger` (qué regla lo disparó), `spec` (copia de la
  especificación usada), `window_days` vigente, periodo muestreado,
  `schema_versions`, conteos por estrato y por partición, `dataset_refs` (un
  dataset del catálogo por partición), `content_hash`, `status`
  (`BUILDING`, `READY`, `FAILED`, `ARCHIVED`), `operation_id`, `created_at`.

**`dataset_sampler_state`** — estado del muestreador (singleton): fecha de la
última muestra, alertas maduradas desde entonces, resumen de la distribución
de referencia para el disparador estadístico, y bloqueo de ejecución con
`rev`.

#### Prompts y coordinación

**`agent_prompts`** — prompts del propio agente, versionados (B1.6). No son
los prompts del pipeline de revisión de alertas, que ya viajan dentro de la
configuración versionada.
- Clave: `prompt_name` + `version` (entero).
- `prompt_name`: p. ej. `orchestrator.system`, `chat.insight_extractor`,
  `chat.summarizer`, `subagent.<área>.generator`, `verifier.<tipo>.explainer`.
- Atributos: `content`, `variables` (esquema de las variables permitidas),
  `model_params`, `content_hash`, `status` (`DRAFT`, `ACTIVE`, `RETIRED`),
  `changelog`, `created_by`, `approved_by`, `created_at`. Inmutable: cambiar un
  prompt crea una versión nueva.
- **`agent_prompt_active`** (clave `prompt_name`): puntero a la versión activa,
  cambiado con escritura condicional y auditado; permite revertir sin
  desplegar código.
- Cada `agent_runs`, mensaje del agente y `agent_tool_calls` guarda
  `prompt_ref` = `{name, version, hash}`, y cada paquete registra los prompts
  con que se generó, para poder reproducir un resultado.

**`agent_entity_claims`** — reclamos informativos (no bloqueantes) de una
sesión de optimización sobre entidades, para el aviso de interferencia (BM.8).
- Clave: `entity_key` (p. ej. `configuration#<id>`,
  `library_modus_operandi#<id>`, `scope#<área>`) + `session_id`.
- Atributos: `claimed_at`, `heartbeat_at`, `expires_at`, `reason`
  (alcance declarado o ítem de paquete que la toca).
- Se escribe al arrancar una sesión (por su alcance) y al crear un ítem de
  paquete; se renueva con el heartbeat y caduca si la sesión muere. Consultar
  por `entity_key` devuelve qué sesiones trabajan sobre algo.

#### Confirmaciones

**`agent_confirmations`** — registro append-only de cada confirmación humana
(BM.7), en ambos modos.
- Clave: `session_id` + `confirmation_id`.
- Atributos: `package_id`, `item_id`, `action` (`create`, `update`, `delete`,
  `activate`), `content_hash` y `diff_hash` de lo que el usuario vio,
  `base_version`, `verifier_snapshot` (estado de cada verificador),
  `confirmed_by`/`confirmed_by_id`/`role`, `confirmed_at`, `source_message_id`,
  `consumed_at` y `applied_ref` (cuándo y con qué resultado se usó),
  `status` (`VALID`, `CONSUMED`, `INVALIDATED`).
- Solo se crea con escritura condicional y nunca se borra; lo único que cambia
  es `status`/`consumed_at`. Se conserva 2 años, igual que el resto de los
  elementos del chat (`expires_at` a 730 días, decisión del 2026-10-18).
- GSI: `ItemIdx` (`item_id`, `confirmed_at`) para verificar que un ítem tiene
  una confirmación vigente antes de aplicarlo.

### Políticas y límites fuera de las sesiones

Los topes globales, los kill switches y los parámetros del muestreo viven en
una configuración propia, `AssistantOptimizerSettings`, con el mismo patrón que
`OperationalSettings`: singleton, efecto inmediato, sin versionado de
activación, historial de cambios y auditoría. Se describe en "Configuración del
asistente y del optimizador". Se lee en cada tick y antes de cada llamada a
herramienta. Una sesión puede pedir menos que el tope global, nunca más.

No se usa `OperationalSettings` para estos topes porque ya contiene
`agent_enabled`, que es el interruptor del agente de **revisión de alertas**, y
porque crecería con parámetros que no son interruptores ni dimensionamiento.
`OperationalSettings` y `AssistantOptimizerSettings` solo los modifican
`release_manager` y `manager`. El asistente y el optimizador **no** escriben en
ninguna de las dos ni las proponen como ítem de paquete.

### Runtime y ejecución

- **Cola y worker propios**, siguiendo el patrón de #15: `CELERY_AGENT_QUEUE` y
  un worker `agent-worker`, para que el agente no compita con el procesamiento
  de alertas. Los factories del worker viven en
  `infrastructure/workflows/celery/` y los de la API en
  `entrypoint/api/factories/`; `application/` no importa infraestructura.
- **Tick del orquestador**: tarea `agent.orchestrate_session` que avanza una
  sola iteración y se reencola mientras haya señal y presupuesto. Toma el
  lease de la sesión con una escritura condicional (`lease_owner`,
  `lease_expires_at`, renovado con heartbeat); solo un orquestador actúa por
  sesión.
- **Runs**: cada subagente es un job despachado por el puerto de ejecución
  asíncrona ya existente, con su registro en `async_operations` y su fila en
  `agent_runs`. El estado del agente no se duplica: `async_operations` dice si
  el job corre; `agent_runs` dice qué hace para el agente.
- **Recuperación**: tarea de Beat `agent.recover_stale_runs` (un minuto) sobre
  `StatusLeaseIdx`: reintenta o cierra los runs con lease vencido y libera
  sesiones huérfanas. Todo paso es idempotente (iteración condicional, mensaje
  por `client_message_id`, aplicación de ítems por `approval_status`).
- **Mensaje de chat**: la API persiste el mensaje (idempotente) y despacha la
  tarea `agent.handle_message`; la respuesta del agente se guarda como mensaje
  y el frontend la recibe por polling con `after_seq`. Transporte en vivo
  (SSE) queda como decisión pendiente.
- **El chat nunca espera al orquestador**: `agent.handle_message` no toma el
  lease de la sesión. Escribe el mensaje, responde y registra insights; el
  orquestador los lee en su siguiente tick. Así una sesión de optimización
  sigue conversable mientras corre, y un usuario puede tener varias sesiones
  abiertas (asistente más optimizadores) hasta un tope por usuario
  (`max_sessions_per_user`).
- **Cambios externos durante una sesión**: cuando una entidad viva dentro del
  alcance de un optimizador cambia por mano de un usuario o del asistente, se
  registra un mensaje de sistema en esa sesión, los ítems de paquete con
  `base_version` desfasada se marcan obsoletos y las comparaciones que
  dependían de ella se invalidan. El optimizador trabaja sobre versiones
  fijadas, así que el choque real ocurre al aprobar.
- **Trabajos largos del asistente**: entrenar un modelo o construir un Vector
  Store corre como job asíncrono (run con su `async_operations`), igual que en
  el optimizador. El chat sigue disponible; el progreso aparece en la
  conversación y el resultado vuelve a la sesión como borrador a verificar y
  confirmar. Cuentan contra `optimizer_max_candidates_per_session` y la
  concurrencia global.
- **Retención**: `expires_at` (730 días) en mensajes, llamadas a herramientas,
  insights, enlaces, resúmenes y confirmaciones.
  El TTL no borra en OKD/LocalStack (hallazgo de #22), así que se requiere el
  mismo job de limpieza por `expires_at`.
- **Auditoría**: las mutaciones de estas tablas pasan por los adaptadores de
  auditoría de infraestructura, y cada acción lleva actor y sesión (B1.4).
  Observabilidad: spans con atributos de baja cardinalidad (modo, área, tipo
  de subagente, estado); nunca `session_id` de usuario ni contenido de
  mensajes en atributos de métricas.

### Contrato de API (`/api/v0/agent/...`)

| Recurso | Operaciones |
|---|---|
| `sessions` | crear, listar propias, obtener, iniciar, pausar, reanudar, cancelar |
| `sessions/{id}/messages` | enviar (idempotente), listar con `after_seq` |
| `sessions/{id}/attachments` | subir, listar, borrar |
| `sessions/{id}/insights` | listar, confirmar, editar, rechazar |
| `sessions/{id}/iterations` | listar, obtener (progreso del loop) |
| `sessions/{id}/budget` | consultar; solicitar renovación |
| `sessions/{id}/packages` | listar, obtener con ítems y verificaciones |
| `packages/{id}/items/{item}` | editar borrador, rechazar, confirmar y aprobar (crea el registro en `agent_confirmations`) |
| `sessions/{id}/confirmations` | listar (auditoría) |
| `packages/{id}/approve` | aprobar el paquete completo |
| `objectives` | listar, crear versión, activar |

Todas las respuestas son seguras por contrato (B1.3): sin filas, payloads ni
razonamientos. Los errores son tipados con códigos seguros.

### Qué se crea en cada fase

| Fase | Tablas |
|---|---|
| Columna vertebral (B1, B3.1) | `agent_sessions`, `agent_iterations`, `agent_runs`, `agent_tool_calls`, `agent_budget_ledger`, `agent_verifications`, `agent_packages`, `agent_prompts`, `agent_prompt_active` |
| Chat e insights (B4) | `agent_messages`, `agent_attachments`, `agent_insights`, `agent_links`, `agent_session_summaries` |
| Modo asistente (Fase A) | `agent_confirmations`; usa las anteriores. `agent_attachments` queda fuera de la v1 (solo texto pegado) |
| Configuración y muestreo (Fase S, BC) | `assistant_optimizer_settings` (+ historial), `dataset_snapshots`, `dataset_sampler_state`; deben existir antes de abrir el modo asistente |
| Optimización (B2, B3.2) | `agent_objectives`, `agent_hypotheses`, `agent_findings`, `agent_entity_claims` (el asistente ya la lee desde BM.8) |

### Tareas del modelo de datos

- **BD.1** — Puertos y repositorios de sesiones, iteraciones, runs y
  llamadas a herramientas, con escritura condicional por `rev` y lease.
  *Aceptación:* tests con fakes en memoria y de integración contra DynamoDB
  Local; recuperación tras reinicio.
- **BD.2** — Puertos y repositorios de paquetes, ítems y verificaciones.
  *Aceptación:* un paquete sellado rechaza cualquier escritura posterior.
- **BD.3** — Puertos y repositorios de mensajes, adjuntos, insights, enlaces y
  resúmenes. *Aceptación:* un reintento con el mismo `client_message_id` no
  duplica; consulta de insights activos por alcance sin `Scan`.
- **BD.4** — Presupuesto: ledger, contadores atómicos y topes globales en
  `AssistantOptimizerSettings`. *Aceptación:* dos runs concurrentes no pueden
  superar el tope.
- **BD.5** — Alta de tablas en `manager.py`, respaldos, `e2e_state_cleaner`,
  OKD y job de limpieza por `expires_at`. *Aceptación:* `make
  test-architecture` y `make lint` verdes sin ampliar baselines.
- **BD.6** — Tests de arquitectura y de fuga: ninguna de estas tablas guarda
  filas del dataset ni errores crudos (valores señuelo, B7.2).

## Configuración del asistente y del optimizador

Decidido (2026-10-18): un menú dentro de las configuraciones del manager para
manipular el asistente, el optimizador y el resto de parámetros acordados
(ventana de maduración, disparadores del muestreo, límites del objetivo,
retención, kill switches). Incluye backend y experiencia de usuario.

### Backend

- **Entidad**: singleton `AssistantOptimizerSettings` (puerto
  `assistant_optimizer_settings_port.py`, tabla propia y tabla de historial),
  con el patrón de `OperationalSettings`: `get`/`update`, efecto inmediato, el
  diff se calcula en el caso de uso, cada cambio queda en el historial con
  autor y hora, y pasa por la auditoría de infraestructura.
- **Ventana de maduración**: se queda en `OperationalSettings` porque la leen
  también las métricas y el reentrenamiento. El menú la muestra junto al resto
  como una sección más; cada sección guarda contra su propio endpoint.
- **Roles**: editan `release_manager` y `manager`. `channel_manager` no tiene
  el menú ni modifica estas metaconfiguraciones: solo **activa** el optimizador
  y toma las decisiones que el agente le escala (decisión 23).
- **API**: `GET` y `PUT /api/v0/assistant-optimizer-settings`,
  `GET .../changes` (historial) y `POST .../sampler/preview` (BS.8).
- **Validación en servidor**: rangos, coherencia entre campos (por ejemplo, la
  suma de proporciones de particiones) y topes que una sesión no puede superar.

### Secciones y parámetros

| Sección | Parámetros |
|---|---|
| Asistente | `assistant_enabled`, `assistant_max_message_chars` (8.000), `assistant_max_messages_per_session`, `max_sessions_per_user`, `chat_retention_days` (730) |
| Optimizador | `optimizer_enabled` (kill switch), `optimizer_max_concurrent_sessions`, `optimizer_max_concurrent_runs`, `optimizer_max_candidates_per_session`, `optimizer_session_budget_ceiling` (tokens, USD, segundos), política de renovación de presupuesto (siempre con aprobación; máximo de renovaciones), iteraciones sin mejora antes de parar |
| Objetivo y límites | `objective_precision_floor` (piso de precisión; el recall se maximiza), soporte mínimo por segmento, conteo mínimo para publicar agregados, cobertura mínima de alertas maduras para declarar ganador, parada ante fallo crítico. Coste y duración por sesión: 50 USD y 12 horas; escalamiento informativo (decisión 2) |
| Maduración del fraude | `maturing_days`, `expected_coverage_pct`, `stable_months` (en `OperationalSettings`) |
| Muestreo de datos | `sampler_enabled`; disparadores (periodo, volumen N, umbral estadístico, enfriamiento); periodo de muestreo en días; tamaño o margen de error y confianza; estratos; mínimo por estrato; razón de sobremuestreo de fraude; proporciones de particiones; política de semilla; máximo de muestras retenidas; versiones de esquema compatibles; por esquema, selección de campos de marca vigente, fecha de última marcación, marca inicial y fecha inicial desde el pool de campos del esquema, más mapeo configurable de valores a fraude/no fraude |

Los valores del objetivo y del muestreo son **valores por defecto y topes**: al
crear una sesión se copian dentro de la versión del objetivo y de cada muestra,
así que un cambio posterior no altera resultados ya producidos.

### Experiencia de usuario

- Nueva pestaña **"Asistente y optimizador"** en `/configuracion`, junto a
  "Operación (inmediata)". Es una de las pestañas del manager y del release
  manager. Se construye como componente propio (`AgentSettingsPanel`), no dentro
  del archivo de la ruta, que ya supera las 2.700 líneas.
- Una tarjeta por sección, con la insignia "efecto inmediato", quién y cuándo
  hizo el último cambio, y guardado por sección.
- Validación en línea con el mismo mensaje que devuelve el servidor.
- **Confirmación con explicación** para cambios de alto impacto: apagar un kill
  switch, cambiar la ventana de maduración (afecta los avisos del monitoreo y
  las muestras siguientes, no las ya producidas) o subir un tope.
- **Vista previa del muestreo** dentro de la sección de muestreo: conteos por
  estrato, tamaño estimado y disparadores que se activarían hoy.
- Historial de cambios en un panel lateral y valores por defecto restaurables.
- Modo solo lectura cuando la API no responde, como el panel de operación.
- Etiquetas y ayudas en español, con un ejemplo concreto en los parámetros que
  se prestan a confusión (ventana, periodo de muestreo, piso de precisión).

### Tareas

- **BC.1** — Puerto, repositorio e historial de `AssistantOptimizerSettings`;
  caso de uso de lectura y actualización con diff y auditoría.
- **BC.2** — API, validaciones en servidor y permisos por rol.
- **BC.3** — Mover la lectura de ventana de maduración de `range_planner` a
  `OperationalSettings` y añadir sus campos y validación.
- **BC.4** — Que el asistente, el orquestador y el muestreador lean la
  configuración en cada tick (sin caché larga), con pruebas de efecto
  inmediato: apagar `optimizer_enabled` detiene las sesiones en el siguiente
  tick; bajar `assistant_max_message_chars` rechaza el mensaje siguiente.
- **BC.5** — Pestaña de interfaz (FP1b) con pruebas E2E reales.

## Orden de implementación

El orden sigue tres criterios: primero lo que ya aporta valor al producto
actual y no depende del agente; luego la columna vertebral con el modo
asistente completo; y al final el optimizador, que es lo que más decisiones
abiertas tiene. Cada hito deja algo utilizable y verificable.

**Reglas comunes a todos los hitos**
- `make lint` y `make test-architecture` sin crecer los baselines; pytest del
  código tocado; E2E Playwright real contra el stack reconstruido, a través de
  nginx, antes de darlo por terminado (`CLAUDE.md`).
- Cada tabla nueva entra en `manager.py`, en el catálogo de respaldos, en el
  `e2e_state_cleaner` y en el aprovisionamiento de OKD.
- Cada hito actualiza `PENDIENTES.md` §8 y este documento.
- Un puerto por entidad, fakes en memoria en los tests, sin `unittest.mock`.

### H0 — Verificaciones previas (sin construir)
Cerrar lo que el diseño asume sin haberlo comprobado: dónde se arma el dataset
de entrenamiento y si ya filtra por madurez; si el catálogo de datasets sirve
para la muestra del muestreador; qué rol aprueba la activación de
configuraciones; guías del frontend; estado del aprovisionamiento de tablas en
OKD. Resultado: una nota en este documento con lo hallado.
*Depende de:* nada.

**Resultado H0 (2026-10-18, verificado en código):** el worker entrena con
todas las filas del dataset del modelo; no aplica filtro de madurez. El
entrenamiento recibe un solo dataset y vuelve a crear las particiones
`training`, `validation`, `calibration` y `test`, así que no consume sin cambios
cuatro datasets particionados del catálogo. La solicitud de activación la crea
`channel_manager`; solo `manager` o `release_manager` aprueban y quien la creó
no puede aprobarla. En OKD las tablas se aprovisionan dinámicamente por
`ensure_all_tables()` al iniciar la API cuando existe `DYNAMO_ENDPOINT`; esto
no confirma el estado de un clúster concreto. H0 no requiere pruebas ni E2E.

### H1 — Ventana de maduración configurable
Campos `maturing_days`, `expected_coverage_pct` y `stable_months` en
`OperationalSettings`, validación y API; `range_planner` los lee en lugar de las
constantes (BC.3). Se muestran provisionalmente en el panel de operación
existente. Más percentiles en el análisis de marcado para elegir el valor.
*Valor:* el monitoreo ya usa una ventana ajustable.
*Depende de:* nada.

### H2 — Menú "Asistente y optimizador" (BC.1, BC.2, FP1b)
Singleton `AssistantOptimizerSettings` con historial y auditoría, API, y la
pestaña de Configuración para manager y release manager con todas las
secciones (asistente, optimizador, objetivo y límites, maduración, muestreo).
En este hito los parámetros del muestreo y del optimizador se guardan pero aún
nada los usa. La vista previa del muestreo (BS.8) queda para H6.
*Depende de:* H1 (muestra la ventana).
*Se verifica con:* E2E que guarda un cambio y lo ve con efecto inmediato.

### H3 — Columna vertebral mínima
Tablas y puertos de sesiones, iteraciones, runs, llamadas a herramientas,
ledger de presupuesto, verificaciones, paquetes y confirmaciones, más el
registro de prompts versionados (BD.1, BD.2, BD.4, B1.1 a B1.6). Contrato de
subagente con un subagente de prueba (B3.1). Orquestador mínimo de una
iteración. Cola y worker propios del agente, lease, barrido de recuperación,
lectura en cada tick de los kill switches y topes de H2, API de sesiones y
paquetes (B1.5).
*Depende de:* H2.
*Se verifica con:* una sesión de prueba con el subagente stub que se pausa, se
cancela, se recupera tras matar el worker y respeta el kill switch.

### H4 — Chat, insights y panel base
Mensajes con idempotencia, enmascarador de datos personales, límites de
tamaño, insights con su ciclo de vida, enlaces y resúmenes de sesión
(BD.3, B4.1 a B4.6, BM.1, BM.6). Frontend: cascarón del panel en
`DashboardLayout`, hooks y cliente de API, kit de chat con tarjetas de
insights (FP1, FP2).
*Depende de:* H3.
*Se verifica con:* pruebas de fuga con valores señuelo, inyección de prompt y
un E2E del chat con reintento sin duplicados.

### H5 — Modo asistente v1: Biblioteca
Subagente generador, verificadores ligeros, borrador con procedencia de campos,
edición, diff y confirmación auditada (BM.2, BM.3, BM.4, BM.7, FP3). Se
entrega por tipo de entidad, empezando por **modus operandi con playbook** y
siguiendo con taxonomías, casos similares, watchlists, flags y el resto de la
Biblioteca; cada tipo trae su verificador.
*Depende de:* H4.
*Se verifica con:* E2E real de crear y de editar una entrada, con la
confirmación registrada en `agent_confirmations` y en la auditoría.

### H6 — Muestreo de datos maduros (Fase S)
Elegibilidad y filtro de madurez, disparadores (semanal por defecto),
muestreo estadístico, particiones, snapshots inmutables materializados como
datasets del catálogo, ejecución con Beat y Celery, y vista previa
(BS.1 a BS.8). Se conecta el reentrenamiento para que use solo muestras
maduras.
*Depende de:* H1, H2 y la verificación de H0. Puede construirse en paralelo con
H3 a H5.
*Se verifica con:* misma especificación, mismo periodo y misma semilla dan la
misma muestra; ninguna alerta inmadura ni `pending` aparece.

### H7 — Modo asistente: configuración, Vector Stores y modelos
Borradores de configuración versionada (se activan por el flujo de
solicitudes de despliegue), construcción de generaciones de Vector Store y
entrenamiento de modelos XGBoost sobre una muestra, con construir y activar
como confirmaciones separadas. Jobs largos con progreso en el chat.
*Depende de:* H5 y H6.

### H8 — Decisiones y evaluación del optimizador
Cerrar las decisiones abiertas (2 a 8) y B0.2, B0.3 y B0.4. Objetivos versionados
(`agent_objectives`), evaluador global sobre muestras maduras, verificación por
etapa y ruta, comparación estadística contra baseline, protección de la
partición final, diagnóstico agregado y descubrimiento de patrones
(B2.1 a B2.6).
*Depende de:* H6, H3 y las decisiones.
*Se verifica con:* resultados reproducibles para versiones fijadas y ninguna
fila por caso en las respuestas.

### H9 — Orquestador del optimizador
Ciclo largo persistido con hipótesis, ranking y criterios de parada
deterministas, cierre insight → evidencia, memoria de sesión, reclamos de
entidad y aviso de interferencia (BM.8), renovación de presupuesto,
detección de estancamiento y kill switch (B3.2, B4.4, B4.5, B7.3).
Frontend: activación desde el panel, pestaña del optimizador, progreso y
aviso de interferencia (FP4, FP5).
*Depende de:* H8 y H4.

### H10 — Subagentes del optimizador
Uno por área, cada uno con su verificador antes de dejarlo actuar: configuración
del agente, Biblioteca, Vector Store y modelo XGBoost (B5.1 a B5.4). El primero
se decide en la decisión 8 (candidato: configuración del agente, por ser el
más medible con lo existente).
*Depende de:* H9.

### H11 — Combinaciones, revisión y operación
Evaluación de combinaciones (B3.3), vista de comparación y aprobación por ítem
o por paquete (FP6), herramientas operativas, historial y auditoría en la
interfaz (FP7, F7.4), observabilidad del agente (B7.1).
*Depende de:* H10.

### H12 — Validación y salida gradual
Evaluación retrospectiva, shadow mode, promoción gradual con rollback
(X8.1 a X8.3) y E2E de punta a punta del optimizador (FP8).
*Depende de:* H11.

### Qué se puede hacer en paralelo
- H1 y H0 pueden empezar ya.
- H6 (muestreador) corre en paralelo con H3 a H5 una vez cerrados H1 y H2.
- Dentro de H5, los tipos de entidad avanzan por separado.
- H8 puede arrancar en cuanto estén las decisiones abiertas y H6 listo, aunque
  H5 y H7 sigan en curso.

## Planificación de frontend

Alcance: el modo asistente y el modo optimizador, sobre `frontend_mockup`
(TanStack Router con rutas planas por archivo, TanStack Query, hooks por
recurso, clientes en `src/lib/api/*.functions.ts`, roles en `useRole`).
Esta sección planifica etapas; las pantallas y componentes finales se definen
en FP0.

### Decisiones de interfaz (2026-10-18)

- El asistente es un **panel lateral derecho superpuesto**, visible en
  Configuración, Testing, Biblioteca y Modelos. No es una ruta.
- El optimizador **no tiene pantalla propia**: es un flujo agéntico
  transversal que se **lanza desde el panel** y aparece como una conversación
  (pestaña) más, con su progreso.
- El optimizador **no bloquea el chat**: se puede seguir conversando con el
  asistente mientras corre.
- El asistente también puede editar la configuración del agente; cuando hay un
  optimizador trabajando sobre lo mismo, muestra un **anuncio** de que otro
  agente está trabajando y puede interferir.

### Dónde encaja en la aplicación

- **Panel**: se monta a nivel de `DashboardLayout`, por encima del contenido,
  y se activa solo en las rutas habilitadas y para los roles autorizados. Un
  botón flotante lo abre y lo cierra. El estado del panel (abierto, pestaña
  activa) es del frontend; las conversaciones son sesiones del backend y se
  recuperan al recargar.
- **Pestañas = conversaciones**: "Asistente" (siempre disponible) y una pestaña
  por cada sesión de optimización lanzada. Varias pueden estar abiertas a la
  vez. Cada pestaña de optimizador contiene el chat de esa sesión y una vista
  de progreso (iteraciones, hipótesis, presupuesto, runs, paquetes).
- **Lanzar el optimizador**: desde la pestaña "Asistente" (o un atajo del
  panel). El `channel_manager` solo **activa**: el objetivo, el presupuesto y
  los límites vienen de la configuración del manager y se muestran como
  resumen de solo lectura; lo único que puede indicar es el alcance (qué
  áreas) y notas o insights iniciales. Termina en un resumen y un botón
  explícito "Iniciar", porque una sesión consume presupuesto. El asistente también puede proponer lanzarlo
  desde la conversación; el inicio siempre lo confirma el usuario.
- **Estado de cada pestaña**: ejecutando, esperando tu respuesta, requiere
  aprobación, terminó, falló o detenido. Un indicador en la pestaña y en el
  botón flotante avisa de lo que necesita atención aunque el panel esté
  cerrado.
- **Anuncio de interferencia**: si la página o entidad que el usuario está
  editando entra en el alcance de una sesión de optimización activa, el panel
  y el editor muestran un aviso con qué agente trabaja, sobre qué y desde
  cuándo. Es informativo, no bloquea. Al guardar o aplicar se vuelve a
  comprobar la versión base.
- **Contexto de página**: el panel envía la ruta y la entidad seleccionada como
  referencias (ids), nunca el contenido de la pantalla, para que el asistente
  actúe sobre lo que el usuario está viendo.
- **Revisión de paquetes**: el panel es estrecho para diffs, así que la
  revisión se abre en una vista ampliada (el panel se expande o abre una
  superposición grande) sin salir de la página.
- **Roles**: el panel aparece donde el rol ya ve esas rutas (`ROLE_NAV`). El
  asistente exige los permisos de creación manual de cada entidad. El
  optimizador solo lo puede lanzar `channel_manager` (decisión 15); el backend
  lo impone.
- **Carpeta compartida**: `src/components/agente/`.

### Piezas reutilizables y nuevas

| Pieza | Origen |
|---|---|
| Polling de progreso | patrón de `useAsyncOperation` (2 s, se detiene en estado terminal) |
| Tarjeta de progreso de operación | `AsyncOperationProgressCard` |
| Vista y diff de configuración | `ConfigurationVersionGuide` y el flujo de solicitudes de despliegue |
| Detalle de playbook de modus operandi | `ModusOperandiPlaybookModal` |
| Gráficas y filtros de métricas | `components/metrics/*` (revisar la guía `dataviz`) |
| Contenedor del panel y pestañas | nuevo, montado en `DashboardLayout` |
| Panel de chat y lista de mensajes | nuevos |
| Tarjeta de insight, panel de insights | nuevos |
| Insignia de procedencia de campo | nuevo |
| Resultados de verificadores | nuevo |
| Aviso de interferencia | nuevo |
| Formulario de lanzamiento del optimizador | nuevo |
| Línea de tiempo del loop, medidor de presupuesto | nuevos |
| Diff por tipo de ítem y diálogo de confirmación | nuevos |

### Etapas

**FP0 — Descubrimiento y diseño de interacción**
Leer las guías del frontend (`CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`) y las
decisiones UX previas. Definir flujos de ambos modos, bocetos del panel y de
las pestañas, textos en español, estados vacíos, de carga, de error y de
límite alcanzado, y accesibilidad (foco, teclado, lectores de pantalla en un
panel superpuesto). Resolver: ancho del panel y comportamiento en pantallas
pequeñas, cómo se ve la vista ampliada, qué indicadores usa la pestaña y si
el panel recuerda su estado entre rutas.
*Entregable:* documento de flujos y bocetos revisado con el usuario.

**FP1 — Cimientos y cascarón del panel**
Cliente `agent.functions.ts` con tipos de la API, archivo de mapeo como
`metricsMapping.ts`, hooks por recurso (`useAgentSession`, `useAgentMessages`
con `after_seq`, `useAgentInsights`, `useAgentPackage`, `useAgentProgress`),
contenedor del panel con pestañas montado en `DashboardLayout`, control por
rol y por ruta, y bandera de característica que lo oculta si `assistant_enabled`
está apagado. Pruebas de contrato con Vitest.
*Aceptación:* el panel se abre y se cierra en las cuatro rutas y solo para los
roles autorizados; tipos alineados con la API real.

**FP1b — Menú de configuración del asistente y del optimizador**
Pestaña "Asistente y optimizador" en `/configuracion` (manager y release
manager), con el componente `AgentSettingsPanel` fuera del archivo de la ruta.
Secciones y parámetros de "Configuración del asistente y del optimizador",
guardado por sección, confirmaciones con explicación, vista previa del
muestreo, historial de cambios y solo lectura si la API no responde. Muestra la
ventana de maduración (de `OperationalSettings`) como una sección más.
*Aceptación:* un cambio guardado surte efecto inmediato (por ejemplo, apagar el
optimizador); un valor inválido se rechaza con el mensaje del servidor; el
`channel_manager` no ve esta pestaña. Va antes de abrir el modo asistente, para
que los kill switches y los topes existan desde el primer día.

**FP2 — Kit de chat compartido**
Chat con envío idempotente (`client_message_id`), estado optimista, reintento,
límite de tamaño del texto, tarjetas de insights propuestos con confirmar,
editar y rechazar, y vista del resumen de sesión. Estado "esperando al
usuario" visible.
*Aceptación:* un mensaje reenviado tras un fallo de red no se duplica; ningún
contenido por caso se muestra.

**FP3 — Modo asistente en el panel**
Pestaña "Asistente": conversación, contexto de página, borrador de la entidad
(Biblioteca, configuración del agente, Vector Store o modelo) con insignias de procedencia por
campo, resultados de los verificadores, edición directa o por chat, diff para
ediciones y diálogo de **confirmación explícita** (BM.7) que muestra
exactamente lo que se aplicará. Al confirmar, la entidad aparece o se
actualiza en la página.
*Aceptación:* un fallo de verificador bloquea la confirmación hasta corregirlo
o aceptarlo de forma explícita; un "sí" en el chat no confirma; solo se
ofrecen entidades que el rol puede modificar.

**FP4 — Lanzar el optimizador desde el panel**
Activación del optimizador: alcance (qué áreas) y notas iniciales, más un
resumen de solo lectura con el objetivo vigente, el presupuesto y los límites
definidos por el manager, y un aviso claro de qué puede modificar el agente y
qué no. Confirmación de inicio. La sesión nueva aparece como pestaña. Cuando
el agente escala una decisión, aparece en esa pestaña como una tarjeta que el
`channel_manager` resuelve.
*Aceptación:* el `channel_manager` no puede cambiar presupuesto ni límites;
el asistente sigue usable mientras se crea y arranca la sesión.

**FP5 — Pestaña del optimizador: conversación y progreso**
Chat de la sesión más vista de progreso: hipótesis actual, subagente, línea de
tiempo de iteraciones, estado de verificación, presupuesto gastado y restante,
motivo de parada, y controles de pausar, reanudar y cancelar. Indicadores de
atención en la pestaña y en el botón flotante. Aviso de interferencia
(compartido con FP3).
*Aceptación:* varias pestañas conviven sin bloquearse; el chat responde
mientras el loop corre; los estados (ejecutando, esperando, requiere
aprobación, completado, fallido, cancelado) se representan correctamente; no
depende de endpoints de detalle por caso.

**FP6 — Comparación, revisión y aprobación**
Vista ampliada: comparar baseline y candidatos (métrica global,
restricciones, resultados por área y segmento, incertidumbre, cobertura de
etiquetas, suficiencia de muestra) y diff por tipo de ítem del paquete.
Confirmación por ítem o por paquete, que dispara los flujos de activación
existentes según el rol, con rastro de autor y aprobador.
*Aceptación:* queda clara la diferencia entre mejora local y global; los
candidatos rechazados muestran su motivo; el loop nunca publica.

**FP7 — Operación y seguridad en la interfaz**
Kill switch y estado global, límites alcanzados, solicitud de renovación de
presupuesto, fallos seguros con códigos explicados, historial y auditoría de
sesiones y confirmaciones, y estados de sesión caducada o en lease perdido.
Revisión de accesibilidad y rendimiento (listas largas de mensajes e
iteraciones).

**FP8 — E2E real y endurecimiento**
Cada cambio de frontend actualiza su cobertura Playwright y la corre contra el
stack local reconstruido, a través de nginx y con el proxy `/api/...`, como
exige `CLAUDE.md`. Se añaden `e2e/agent-assistant-real.spec.ts` y
`e2e/agent-optimizer-real.spec.ts` con su script `test:e2e:agent:real`, además
de pruebas de componentes en `src/test/`. Los escenarios cubren: crear y
editar una entrada de la Biblioteca con el asistente de punta a punta, la
confirmación auditada, lanzar un optimizador y seguir chateando con el
asistente, el aviso de interferencia, un insight confirmado que cambia el
comportamiento del loop, pausa y cancelación, aprobación de un paquete y
bloqueo por rol. Si falta una credencial, Docker o datos de fixture, se
reporta el bloqueo exacto y el cambio queda incompleto; no se da por pasada
una prueba de otro escenario.

### Dependencias con el backend

| Etapa de frontend | Necesita |
|---|---|
| FP1 | API de sesiones y mensajes con tipos estables (B1.5) |
| FP1b | BC.1–BC.3 (configuración y su API) y BS.8 (vista previa del muestreo) |
| FP2 | BD.3, B4.1–B4.3, límite y redacción del texto (BM.1) |
| FP3 | Fase A completa (BM.2–BM.4, BM.7, BM.8) |
| FP4 | `agent_objectives`, BD.4 y B0.2 |
| FP5 | B3.2, BD.1, reclamos de entidad (BM.8) |
| FP6 | B1.2, BD.2, B2.1–B2.3 y flujos de aprobación |
| FP7 | B7.3 y topes en `AssistantOptimizerSettings` (BC) |
| FP8 | Stack local reconstruible y fixtures de prueba |

El modo asistente (FP1 a FP3) se entrega antes que el optimizador (FP4 a FP6);
FP2 y FP5 comparten el chat y el panel de insights, así que el kit común se
construye una sola vez.

## Decisiones pendientes

1. ✅ **Resuelta 2026-10-18** (B0.1): `fraud_label` tras la ventana de
   maduración del fraude (entidad configurable); las alertas inmaduras no las
   usan el agente ni el reentrenamiento (el monitoreo sí las muestra); métrica principal precisión y recall por conteo. La ventana es única
   (decidido: el comportamiento es casi indistinguible entre canales).
2. ✅ **Resuelta 2026-10-18:** recall maximizado con piso de precisión
   configurable; tope de 50 USD y 12 horas por sesión; el optimizador está
   apagado por defecto y se detiene ante el primer fallo crítico. El
   escalamiento es informativo.
3. ✅ **Resuelta 2026-10-19 (volumen e historia disponibles):** unos 50.000
   registros maduros/mes, con 2–4 % de fraude; existen cinco años de historia,
   pero la extracción disponible cubre unos seis meses. El muestreador usará
   como máximo esos seis meses disponibles y excluirá etiquetas no clasificables
   o pendientes. La marca vigente y su fecha de última marcación determinan la
   clase y madurez; la marca/fecha iniciales son inmutables. El mapeo no
   codificará nombres de columnas: el manager los seleccionará del pool del
   esquema y configurará los valores de fraude/no fraude. Queda por confirmar
   si `fraud_label_reviews` captura toda remarcación de origen; no se necesita
   ese historial para muestrear el estado vigente.
4. ✅ **Resuelta 2026-10-19:** al agotarse el tope vigente se pausa la sesión;
   el `channel_manager` puede autorizar ampliaciones adicionales, una por una.
   Cada ampliación queda auditada, no es automática y respeta
   `optimizer_max_budget_renewals`.
5. ✅ **Resuelta 2026-10-19:** el `channel_manager` aprueba/rechaza el paquete
   completo del optimizador. La promoción a producción requiere aprobación de
   `manager` o `release_manager` y sigue separada de aprobar el paquete.
6. ✅ **Resuelta 2026-10-19:** mostrar diagnósticos a nivel de segmento; ocultar
   las métricas de cualquier segmento con menos de 30 casos.
7. ✅ **Resuelta 2026-10-19:** crear `optimizer_insights` para guardar y
   recuperar hallazgos agregados respaldados por datos, separados de los
   insights conversacionales por sesión. No requieren confirmación humana caso
   por caso; se guardan con segmento, periodo, tamaño de muestra, versión de
   esquema/mapping y referencias al snapshot/hallazgo. Solo se publican con al
   menos 30 casos por segmento, se reevalúan en cada sesión nueva y pueden
   quedar `SUPPORTED`, `REFUTED`, `STALE` o `RETIRED`. Persistir un hallazgo no
   lo aprueba ni promueve a producción.
8. Para el loop de optimización: ¿qué subagente va primero, tras el modo
   asistente?
9. ✅ **Resuelta 2026-10-18.** Modo asistente: solo texto pegado, sin
   archivos en la v1. El tamaño y los datos personales se resolvieron en la 19.
10. ✅ **Resuelta 2026-10-18.** Modo asistente: toda la Biblioteca, crear y
    editar (y proponer eliminar). Siempre con confirmación explícita
    auditada (BM.7). "Todas las estrategias" se resolvió en la 16 y la 18.
11. ✅ **Resuelta 2026-10-18.** Modo asistente: los mismos roles que crean a
    mano; el asistente no da más permisos.
12. ✅ **Resuelta 2026-10-18.** Chat: polling con `after_seq`.
13. ✅ **Resuelta 2026-10-18** (retención): 2 años para mensajes, llamadas a
    herramientas, confirmaciones y el resto de elementos del chat; no se
    espera mucho volumen. El contenido se guarda redactado (decisión 19).
14. Adjuntos: fuera de la v1 (solo texto pegado). Se retoma si más adelante se
    aceptan archivos.
15. ✅ **Resuelta 2026-10-18** (forma): panel lateral derecho superpuesto en
    Configuración, Testing, Biblioteca y Modelos; el optimizador es un flujo
    transversal que se lanza desde el panel y se ve como una conversación
    (pestaña) con su progreso, sin bloquear el chat. Solo `channel_manager`
    puede **lanzar** un optimizador (decidido 2026-10-18).
16. ✅ **Resuelta 2026-10-18**: el asistente también edita la configuración
    del agente, con un anuncio de que un agente optimizador está trabajando y
    puede interferir (BM.8).
17. ✅ **Resuelta 2026-10-18** (prompts del agente, B1.6): los gestionan los
    desarrolladores, sin interfaz de edición ni rol de usuario para ello, y por
    ahora no se evalúan antes de activarse. Se versionan solo los prompts del
    agente nuevo; los del pipeline de alertas siguen dentro de la
    configuración versionada.
18. ✅ **Resuelta 2026-10-18** (alcance del asistente): la Biblioteca, las
    configuraciones versionadas, los Vector Stores y los modelos XGBoost.
    `OperationalSettings` solo lo tocan `release_manager` y `manager`, así que
    ni el asistente ni el optimizador lo modifican ni lo proponen.
19. ✅ **Resuelta 2026-10-18** (datos personales): se enmascaran antes de
    llegar al modelo y de guardarse; el original no se conserva (ver BM.1).
    Tamaño por mensaje: 8.000 caracteres por defecto, configurable
    (`assistant_max_message_chars`); ver el dimensionamiento en `agent_messages`.
20. ✅ **Resuelta 2026-10-18**: el panel también aparece en `/modelos`, donde
    se gestionan los modelos XGBoost (ver decisión 18).

21. ✅ **Resuelta 2026-10-18**: el muestreador se dispara **una vez por
    semana** por defecto. Los otros disparadores (volumen, estadístico,
    manual) siguen disponibles pero apagados por defecto (mi lectura; se
    enciende cada uno desde el menú).
22. ✅ **Resuelta 2026-10-18**: la muestra se materializa como dataset del
    catálogo actual. Queda como verificación de implementación comprobar que
    el flujo de entrenamiento lo consume sin cambios.
23. ✅ **Resuelta 2026-10-18**: editan el menú `release_manager` y `manager`
    (son metaconfiguraciones). El `channel_manager` no lo ve: solo activa el
    optimizador y decide lo que el agente le escala. Mi lectura, por
    confirmar: puede elegir el alcance y dejar notas al activar, y ve el
    presupuesto y los límites vigentes como resumen de solo lectura.
24. ✅ **Resuelta 2026-10-18** (BS.1): entran alertas maduras, con `mark`
    distinto de `pending`, de todos los canales y de versiones de esquema
    compatibles entre sí. Queda por definir qué versiones del esquema de
    alerta se consideran compatibles; es un detalle técnico que se resuelve
    al implementar BS.3 con el gobierno del esquema.

## Recomendación

Construir primero la columna vertebral (sesión persistida, paquete candidato,
`verify` y orquestador con un subagente stub) y el chat con su modelo de
insights, porque definen los contratos que todos los especialistas
consumirán. Los especialistas se añaden después, de uno en uno, cada uno con
su verificador antes de dejarlo actuar.

El modo asistente es el primer vertical: cubre toda la columna vertebral con
una sola entidad y un verificador ligero, entrega valor inmediato y permite
validar los contratos antes de apostar por el ciclo prolongado de
optimización.
