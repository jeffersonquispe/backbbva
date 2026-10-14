# Backlog: agente de optimización de ARIA

## Objetivo

Construir un agente que optimice el pipeline completo de ARIA y pueda trabajar
sobre los subsistemas habilitados: configuraciones, modelos XGBoost y Vector
Stores. El agente propone y evalúa candidatos en un entorno controlado; un
evaluador determinista verifica cada etapa y el resultado global. El agente
puede recomendar un resultado, pero no activarlo ni promoverlo en producción
por cuenta propia.

Este backlog se basa en el estado observado de `backend` y `frontend_mockup`.
No introduce cambios en contratos actuales hasta que se acuerden las decisiones
de negocio indicadas al final.

## Estado actual relevante

- El flujo de revisión tiene diez pasos potenciales, saltos por reglas y
  detector, y loops adversariales. XGBoost es una señal del detector o del
  clasificador, no una etapa independiente.
- El backend entrena XGBoost de forma asíncrona en un worker separado. Un modelo
  entrenado no se reentrena: cada candidato requiere un modelo nuevo.
- El informe de entrenamiento ya incluye cuatro particiones, métricas por
  umbral, curvas, importancia de variables, parámetros efectivos y hash del
  dataset.
- Las pruebas del pipeline computan métricas de duración por etapa, acuerdo con
  marcación de analista y comparación con desenlace maduro. Los detalles de
  casos pueden incluir datos de entrada/salida y no deben entregarse al agente.
- Configuraciones y Vector Stores cuentan con versionado y flujos de prueba o
  promoción. La activación de modelos y promoción de Vector Stores son acciones
  explícitas separadas.
- No existe aún una función canónica de efectividad global ni una plataforma de
  experimentos del agente.

## Principios de diseño

1. El loop común coordina experimentos; evaluadores especializados verifican
   cada subsistema.
2. La efectividad global se calcula sobre el resultado final y una función
   objetivo versionada. No se promedian métricas incompatibles.
3. Los datos permanecen en workers con acceso autorizado. El agente recibe
   métricas agregadas y referencias opacas, nunca filas, payloads o documentos.
4. Todo candidato fija versiones, dataset, protocolo y presupuesto para que
   sus resultados sean reproducibles.
5. La experimentación y la publicación son fases distintas. Promover requiere
   aprobación y deja auditoría.
6. Las decisiones del loop se basan en verificaciones persistidas, no en el
   historial conversacional del LLM.

## Fase 0 — Decisiones y criterios de éxito

### B0.1 — Definir la efectividad global
**Backend + negocio**

Acordar la etiqueta de éxito, el uso de `fraud_label`, la madurez de las
etiquetas, la métrica principal y las restricciones duras. Definir también
cobertura y soporte mínimo por segmento.

**Aceptación:** función objetivo versionada, con ejemplos agregados y reglas
explícitas para casos sin etiqueta madura.

### B0.2 — Definir política de experimentación y datos
**Backend + seguridad + negocio**

Especificar datasets permitidos, particiones, segmentos, retención, límites de
volumen y presupuesto de cómputo. Asignar roles para crear, consultar, aprobar
y promover experimentos.

**Aceptación:** política aplicable por backend; ningún límite depende de una
instrucción al LLM.

### B0.3 — Clasificar salidas y datos sensibles
**Backend + seguridad**

Revisar resultados por caso, informes, logs y errores para determinar qué
contenido puede revelar datos. El detalle de corridas actual no es una
frontera segura para el agente.

**Aceptación:** contrato de salida segura aprobado, con campos permitidos y
excluidos.

## Fase 1 — Plataforma común de experimentos

### B1.1 — Persistir experimentos y su ciclo de vida
**Backend**

Crear registros para objetivo y versión de métrica, alcance, presupuesto,
estado, baseline, iteración, candidatos, autor, marcas de tiempo y referencias
de artefactos. Reutilizar ejecución asíncrona/Celery donde corresponda. No
persistir filas del dataset en el registro del experimento.

**Aceptación:** experimento auditable y recuperable después de reinicios, con
estados terminales definidos e idempotencia ante reintentos.

### B1.2 — Definir candidatos reproducibles
**Backend**

Registrar referencias exactas a dataset y hash/versión, modelo, configuración,
Vector Store, protocolo y particiones, parámetros y semilla cuando aplique.

**Aceptación:** la comparación muestra qué cambió y qué permaneció constante.

### B1.3 — Implementar el contrato seguro `verify`
**Backend**

Definir una salida tipada de verificación con estado, métricas permitidas,
intervalos o incertidumbre, conteos protegidos por mínimos, versiones,
regresiones, códigos de error seguros y referencias opacas.

Excluir filas, payloads, documentos, prompts, razonamientos, errores crudos e
identificadores sensibles.

**Aceptación:** el agente no puede acceder a datos sensibles por herramientas
alternativas ni obtenerlos mediante errores o logs.

### B1.4 — Aplicar autorización, auditoría y presupuestos
**Backend**

Enforzar roles en endpoints y casos de uso; auditar acciones y lecturas;
imponer límites de candidatos, concurrencia, tiempo y coste en servidor.
Evaluar si se reutilizan los límites de concurrencia y timeout ya presentes
para experimentos de prueba o si el agente necesita presupuesto independiente.

**Aceptación:** el agente no puede ampliar sus límites mediante argumentos de
herramienta y cada acción queda ligada a un actor y experimento.

### B1.5 — Exponer API de experimentos
**Backend + frontend API**

Crear endpoints para crear, iniciar, cancelar, consultar y listar experimentos,
candidatos y verificaciones seguras. Reutilizar el patrón de operaciones
asíncronas para progreso cuando encaje.

**Aceptación:** respuestas autorizadas y libres de datos por caso; cancelación,
idempotencia y errores tipados documentados.

## Fase 2 — Verificadores y comparación

### B2.1 — Evaluador global del pipeline
**Backend**

Calcular la función objetivo contra desenlaces maduros disponibles. Reportar
calidad, cobertura y restricciones por segmentos, junto con número de casos
etiquetados y ventana temporal.

**Aceptación:** resultados reproducibles para versiones fijadas; no se toma la
marcación del analista como verdad de terreno cuando el objetivo sea fraude
real.

### B2.2 — Verificación por etapa y ruta
**Backend**

Medir integridad del flujo: saltos válidos, loops, fallos, escalamiento,
duración y coste; medir calidad solo cuando exista una etiqueta apropiada.
Diferenciar etapa omitida por ruta válida de etapa fallida.

**Aceptación:** la verificación explica agregadamente las rutas recorridas sin
exponer casos individuales.

### B2.3 — Baseline y comparación estadística
**Backend**

Fijar corrida y versiones base; comparar candidatos bajo poblaciones y
protocolos equivalentes. Definir mínimos de muestra e incertidumbre para no
seleccionar ruido como mejora.

**Aceptación:** no se declara ganador con muestra insuficiente o sin alcanzar
el criterio acordado.

### B2.4 — Proteger la partición final de evaluación
**Backend / training worker**

Confirmar que el loop no consulta repetidamente la partición final de test para
escoger parámetros. La evaluación final debe ocurrir después de seleccionar el
candidato, sin retroalimentarse al proceso iterativo.

**Aceptación:** el experimento registra qué particiones fueron consultadas en
cada iteración y reserva la evaluación final.

## Fase 3 — Especialistas y loop coordinador

### B3.1 — Especialista XGBoost
**Backend / training worker**

Crear candidatos nuevos para un dataset específico, explorar parámetros dentro
de rangos aprobados y registrar reporte y protocolo. El modelo activo nunca se
modifica y el agente no recibe reportes crudos que puedan contener datos.

**Aceptación:** presupuesto aplicado, candidatos reproducibles y activación
separada.

### B3.2 — Especialista de configuración
**Backend**

Generar cambios permitidos usando preview/versionado existentes y ejecutar las
pruebas contra una versión fijada. No modificar la versión activa durante la
experimentación.

**Aceptación:** cambios comparables y versión candidata probada antes de poder
activarse.

### B3.3 — Especialista Vector Store
**Backend**

Construir una generación candidata a partir del manifiesto versionado, validar
integridad y calidad de recuperación con consultas autorizadas y retornar
agregados seguros.

**Aceptación:** la búsqueda de evaluación apunta a una generación exacta y no
devuelve documentos al agente.

### B3.4 — Coordinador del loop
**Backend**

Implementar el ciclo persistido: leer verificaciones, formular hipótesis,
escoger subsistema dentro del alcance solicitado, crear candidato, verificar,
actualizar ranking y parar por objetivo, presupuesto, regresión o falta de
señal.

**Aceptación:** cada decisión referencia evidencia; recuperación tras fallo e
idempotencia; criterios de parada deterministas.

### B3.5 — Evaluar combinaciones
**Backend**

Primero medir cambios aislados. Con evidencia, evaluar una combinación de
versiones exactas de modelo, configuración y/o Vector Store de extremo a
extremo.

**Aceptación:** la combinación identifica sus candidatos constituyentes y se
rechaza si rompe restricciones globales.

## Fase 4 — Interfaz de usuario

### F4.1 — Centro de experimentos
**Frontend**

Permitir definir objetivo, dataset autorizado, alcance, presupuesto y
restricciones. Explicar qué puede modificar el agente y qué se evaluará.

**Aceptación:** la interfaz solo ofrece recursos autorizados y refleja límites
aplicados por el backend.

### F4.2 — Progreso del loop
**Frontend**

Mostrar hipótesis resumida, subsistema elegido, candidato, estado de
verificación, progreso, coste acumulado y motivo de parada.

**Aceptación:** usa únicamente APIs seguras, sin depender de endpoints de
detalle por caso.

### F4.3 — Comparar baseline y candidatos
**Frontend**

Mostrar métrica global, restricciones, resultados por subsistema y segmento,
incertidumbre, cobertura de etiquetas y cambios/versiones. Mostrar candidatos
rechazados y su motivo.

**Aceptación:** queda clara la diferencia entre mejora local y global, así como
la suficiencia de muestra.

### F4.4 — Revisar y publicar una recomendación
**Frontend**

Presentar diffs y evidencia `verify`; permitir aprobación explícita y enlazar
con flujos existentes de activación/promoción según rol.

**Aceptación:** el loop no publica; aprobación y promoción se auditan y quedan
ligadas al candidato evaluado.

### F4.5 — Cliente API, estados y permisos
**Frontend**

Añadir tipos y funciones API, polling de progreso, errores seguros y controles
visibles según permisos. El backend sigue siendo autoridad de acceso.

**Aceptación:** pendiente, ejecutando, completado, fallido y cancelado se
representan correctamente.

## Fase 5 — Operación y seguridad

### B5.1 — Observabilidad y auditoría del agente
**Backend**

Registrar experimento, iteración, herramienta, duración, coste y estado con
atributos de baja cardinalidad. Seguir el contrato OTLP existente; no escribir
datos sensibles en spans o métricas.

### B5.2 — Pruebas de fuga de datos
**Backend + seguridad**

Usar valores señuelo en datasets, payloads y errores, y verificar que no
aparezcan en respuestas, trazas, logs ni reportes accesibles al agente.

### B5.3 — Kill switch, cancelación y recuperación
**Backend + operaciones**

Permitir detener iteraciones, cancelar trabajos y recuperar estados tras fallos
sin borrar evidencia requerida para auditoría.

### F5.4 — Herramientas operativas en UI
**Frontend**

Mostrar cancelación, límites alcanzados, fallos seguros, reintentos permitidos,
historial y autor/aprobador de promociones.

## Fase 6 — Validación y salida gradual

### X6.1 — Evaluación retrospectiva

Ejecutar sobre dataset autorizado con baseline fijo, desenlaces maduros y
partición final reservada.

**Aceptación:** mejora defendible sin violar límites globales o por segmento.

### X6.2 — Shadow mode

Ejecutar recomendaciones sin influir en decisiones productivas; comparar
candidato y sistema vigente, observando deriva y coste.

### X6.3 — Promoción gradual y rollback

Requerir aprobación humana, desplegar gradualmente y revertir ante umbrales de
degradación definidos.

## Secuencia recomendada

1. Resolver B0.1–B0.3: objetivo, política de datos y contrato seguro.
2. Construir B1 y B2: experimentos persistidos, `verify`, evaluador global y
   protocolo de comparación.
3. Implementar el primer vertical de XGBoost (B3.1) sobre un dataset autorizado
   y desarrollar la UI de experimento/revisión (F4).
4. Añadir especialistas de configuración y Vector Store.
5. Habilitar el coordinador autónomo y experimentos combinados cuando cada
   subsistema tenga verificaciones confiables.
6. Validar en retrospectiva, shadow mode y luego promoción gradual.

## Decisiones pendientes

1. ¿Qué etiqueta y ventana definen el éxito global? ¿Cómo se trata un caso sin
   `fraud_label` madura?
2. ¿Qué regresiones son límites duros (falsos positivos, escalamiento, coste,
   latencia u otras)?
3. ¿Qué volumen e historia de etiquetas maduras están disponibles?
4. ¿El primer experimento se limita a XGBoost o puede tocar varios subsistemas?
5. ¿Qué roles pueden aprobar y promover candidatos?

## Recomendación

Comenzar con XGBoost como primer vertical de una plataforma genérica de
experimentos, no como un agente aislado. Eso aprovecha el entrenamiento y los
reportes existentes y deja preparada la coordinación para configuración y
Vector Store sin asumir que todos comparten la misma métrica.
