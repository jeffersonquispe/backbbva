# Dashboards y monitores — evaluación y estrategia (#22)

Estado evaluado el 2026-10-01 sobre `feature/version_0_0_3`.

## 1. Qué hay hoy

| Pieza | Estado real |
| --- | --- |
| Trazas | ✅ La app emite spans OTLP (`OpenTelemetryMonitoring`): llamadas LLM con atributos GenAI (`gen_ai.request.model`, `gen_ai.usage.*_tokens`), dependencias como eventos y los use cases `discard`/`escalate`/`execute_alert_action`. Contenido de prompts sólo con `OTEL_CAPTURE_LLM_CONTENT=true`. |
| Métricas | ❌ **La app no emite ninguna métrica**: no hay `MeterProvider` ni instrumentación de FastAPI/Celery. |
| Logs | ❌ Los logs van a stdout y no salen por OTLP, así que el pipeline `logs → Loki` del Collector nunca recibe nada. |
| Grafana local | ⚠️ `service-overview` y `llm-overview` consultan `http_server_request_duration_seconds_*` y `gen_ai_client_*`, que **nadie produce**: los dos dashboards están vacíos. Tempo tampoco tiene `metrics_generator`. |
| OKD | ❌ No hay Collector en el namespace. `OTEL_ENDPOINT=http://localhost:4317` es un placeholder, así que hoy los spans se descartan. |
| `/dashboard` (UI) | ❌ Maqueta con datos fijos o aleatorios: embudo, alertas procesadas, SLA < 5 min, falsos positivos, tiempos por etapa. |
| `/monitor` (UI) | ❌ Maqueta: fraude no detectado, FP, errores, disponibilidad, latencia/tokens ARIA, alucinaciones, contactabilidad de analista y voicebot, % recomendaciones. |
| `/historico-fraude` (UI) | ❌ Maqueta con filas generadas al azar. |
| Alertas/monitores | ❌ No existe ninguna regla de alerta. |

## 2. Principio: dos audiencias, dos fuentes

Hay dos tipos de números que hoy están mezclados:

1. **KPIs de negocio** (`/dashboard`, `/monitor`, `/historico-fraude`): los mira el channel manager o el ops analyst. Tienen que ser **exactos y auditables**: "se procesaron 1.204 alertas ayer" debe coincidir con DynamoDB.
   → **Fuente: los datos de dominio** (`alerts`, `workflow_executions`, `workflow_step_executions`, `resource_reservations`, `feedback`, marcación), servidos por la API de ARIA.
   La app **no** consulta Prometheus. Eso rompería la regla de que OTLP es el único contrato, y además Prometheus agrega y muestrea, con una retención que no sirve para auditoría.

2. **Salud técnica** (SRE/plataforma): latencia, errores, tokens, colas, dependencias caídas.
   → **Fuente: OTLP → Collector → backends** (Prometheus/Tempo/Loki/Grafana en local; lo que BBVA tenga detrás del Collector en OKD). Paneles y alertas viven **fuera** de la app.

Regla práctica: si el número sale en una pantalla de ARIA, viene de la API; si sale en Grafana, viene de OTLP. Ninguno lee del otro. Los indicadores técnicos que se pueden calcular con datos de dominio (tokens, latencias por paso, fallos) también se muestran en la app, calculados desde DynamoDB (ver Fase C).

## 3. Mapa KPI → fuente

| KPI de la UI | Fuente propuesta | ¿Dato disponible hoy? |
| --- | --- | --- |
| Alertas procesadas / embudo (en cola, en proceso, voicebot, analista) | `alerts.status` + `origin` + decisión del executor | ✅ |
| SLA cumplido (< 5 min), tiempos por etapa ARIA / analista / voicebot | `workflow_step_executions` (started/finished) + `resource_reservations` (reserved → released) | ✅ |
| Errores de ejecución / fallos | `workflow_executions.status = FAILED`, alertas `FAILED` | ✅ |
| Procesado por ARIA / analistas / voicebot | decisión del executor + reservas | ✅ |
| Contactabilidad voicebot | `POST /voicebot/callbacks` (`outcome`) | ✅ (sólo con callbacks reales) |
| Latencia y tokens promedio de ARIA | Duración de `workflow_step_executions` + `input_tokens`/`output_tokens` que cada paso LLM ya guarda en su salida (los test runs ya los suman, `test_runs/token_usage.py`) | ✅ |
| Falsos positivos / fraude no detectado | Requiere **ground truth**: marcación (lotes CSV, `MARCACION_FIELD`) o la resolución del analista (bloquear / dejar pasar) | ⚠️ sólo en test runs y alertas resueltas por analista; en producción llega tarde |
| % recomendaciones aceptadas / ignoradas | Decisión del analista vs. recomendación de ARIA en la misma alerta | ✅ (al resolver en `/alerta/$id`) |
| Disponibilidad | Monitor técnico (uptime de `/health`), no KPI de dominio | ❌ (lo da el lado SRE) |
| Alucinaciones / uso correcto de datos | Requiere un evaluador (LLM-judge o reglas sobre citas de evidencia) | ❌ no existe; queda fuera hasta definirlo |

## 4. Propuesta por fases

### Fase A — Que lo técnico deje de estar vacío (sólo configuración, ~½ día)
- Collector: conector `spanmetrics` (viene en la imagen contrib que ya se usa) para derivar RED (rate, errors, duration) por `service.name` + nombre de span desde las trazas que ya existen. **Sin tocar código de la app.**
- Rehacer `llm-overview`/`service-overview` sobre esas series y agregar un panel de "trazas lentas" que salte a Tempo.
- OKD: desplegar un Collector en el namespace (o apuntar al corporativo) y cambiar `OTEL_ENDPOINT`. Sin esto, nada de lo demás llega en OKD. **Bloqueante; depende de plataforma.**

### Fase B — Métricas explícitas donde los spans no alcanzan (~2 días)
- `MonitoringPort` gana contadores e histogramas (mismo adapter OpenTelemetry, `MeterProvider` + exportador OTLP; sin dependencias nuevas, ya están en `opentelemetry-sdk`):
  - `gen_ai.client.token.usage` y `gen_ai.client.operation.duration` (semconv GenAI, los nombres que los dashboards ya esperan).
  - `aria.workflow.duration` por paso y resultado; `aria.alerts.decisions` por decisión/canal/origen.
  - `aria.analyst_queue.depth` y `aria.voicebot.slots_in_use` (observables).
  - `aria.research.calls` (Vector Store / historial) por resultado (`ok`/`failed`/`timeout`).
- Logs por OTLP (`LoggingHandler`) para que Loki reciba y se correlacionen por `trace_id`.

### Fase C — KPIs de negocio y técnicos reales en la UI (diseño acordado 2026-10-01)

La salud técnica que se calcula con datos de dominio (llamadas LLM, errores, tokens, latencia por paso, fallos y timeouts de la investigación, reintentos, rondas adversariales) **también va a la app** con este mismo mecanismo, no sólo a Grafana. A la telemetría sólo le queda lo que no es del negocio (CPU, memoria, pods, conexiones).

#### Niveles de agregado

| Nivel | Retención | Contenido |
| --- | --- | --- |
| **Día** | 90 días (~135k alertas de base, pocas filas) | 24 casillas por hora del día (0–23) |
| **Mes** | 24 meses | 24 casillas por hora del día |
| **Año** | indefinida | 24 casillas por hora del día |

- No hace falta un nivel "hora": las **últimas 24 h** son las casillas de hoy hasta la hora actual más las de ayer desde la hora siguiente.
- **Semana** = 7 filas de día; **Mes** (últimos 30) = 30 filas de día. Los rangos que empiezan hace más de 90 días se ven por mes.
- Las gráficas "Horario diario" (alertas y tiempos 00h–23h) funcionan para cualquier rango, porque cada nivel guarda el perfil por hora.
- Todos los buckets se calculan en **hora de Bogotá** (`OPERATIONS_TIMEZONE`). Los datos crudos siguen en UTC.

#### Sólo medidas acumulativas
- Conteos y sumas, tal cual. Promedios como `suma` + `conteo`. Tasas como numerador + denominador.
- Tiempos (`resolution_time`, latencias) como histograma de rangos fijos (<1 min, 1–5, 5–15, 15–30, >30): dan promedio, % SLA < 5 min exacto y p95 aproximado.
- Nunca se guardan promedios, porcentajes ni conteos de distintos.
- **Frontend**: cada indicador debe decir que se calcula sumando periodos, y no se ofrecen métricas no acumulativas sobre rangos (p. ej. clientes únicos).

#### Maduración del fraude (datos tardíos)
`mark` (la decisión que tomó ARIA, el analista o el voicebot) es inmediata y no cambia. `fraud_` nace igual a `mark` y **puede cambiar** cuando el equipo de fraude conoce la realidad (el cliente llama y confirma o niega el fraude): ~98 % de esos cambios llega en los primeros 4 días y ~2 % en los 6 meses siguientes.
- Cada fila se identifica por la **fecha de la alerta**, no por la fecha en que llega el dato.
- Cada alerta guarda una **foto** de las dimensiones y medidas con las que ya se agregó. Cuando algo cambia (resolución del analista o voicebot en minutos u horas, corrección de `fraud_` en días o meses), se calcula el delta (−foto vieja, +foto nueva) y se aplica con `ADD` atómico a **todos los niveles que aún existen** para esa fecha: día (si tiene < 90 días), mes y año. Así no hay que "cerrar" niveles ni recalcular meses: una marca que llega a los 5 meses corrige directamente su mes y su año.
- El scheduler corre una reconciliación desde las tablas fuente (días de los últimos 90; meses de los últimos 6) como red de seguridad, no como camino principal.
- **Frontend**: los periodos con < 4 días se muestran "en maduración" y los de < 6 meses "pueden variar (~2 %)" en FP y fraude no detectado: mientras nadie corrige `fraud_`, coincide con `mark` y esos KPIs se ven en 0 aunque todavía puedan subir.

#### Campos de filtrado (dimensiones)
`data_type` es la clave principal (`alert`, `workflow_step`, `llm_call`, `research_call`, `reservation`). Cada tipo usa sólo los campos que le aplican.

| Campo | Rol |
| --- | --- |
| segmento, canal, subcanal | dimensión |
| monto | dimensión **por rango** + suma del monto como medida |
| estado | dimensión (estado final) |
| datetime | clave del bucket (día/mes/año) + hora del día |
| `configuration_id` | dimensión |
| `resolution_method` | dimensión: ARIA, analista, voicebot, bidi |
| `mark` | dimensión: decisión tomada (fraude / no fraude) por ARIA, el analista o el voicebot (`resolution_method` dice quién). Inmediata e inmutable. |
| `fraud_` | dimensión: realidad del caso. Nace igual a `mark` y la corrige el equipo de fraude. `mark` × `fraud_` = matriz de confusión: **FP** = `mark` fraude y `fraud_` no fraude; **fraude no detectado** = `mark` no fraude y `fraud_` fraude. Cruzada con `resolution_method` da la calidad de ARIA, de los analistas y del voicebot por separado. |
| `resolution_time` | **medida** (histograma): `marked_at` − llegada de la alerta |
| `marked_at` | cuándo se tomó la decisión (`mark`); también es cuando nace `fraud_` |
| `fraud_reviewed_at` | última revisión del equipo de fraude, **cambie o no** `fraud_` (una confirmación también es maduración); vacío si nunca se revisó |
| tiempo de maduración | **medida** (histograma: < 1 d, 1–4 d, 4–30 d, 1–6 m, > 6 m) = `fraud_reviewed_at` − `marked_at`, contado en el periodo de la alerta. Junto con revisadas / no revisadas y, de las revisadas, cambiadas / confirmadas. |

- **Rangos de monto configurables** en la configuración inmediata (`OperationalSettings`), que genera el enum que clasifica cada transacción. El rango se calcula al recibir la alerta y queda **congelado** en ella: cambiar los rangos sólo afecta alertas nuevas, y el histórico conserva sus etiquetas. La UI avisa cuando un rango de fechas cruza un cambio de rangos.
- Volumen: ~1.5k alertas/día; sólo se guardan las combinaciones que ocurren (cientos de filas por día). "Mes" son 30 lecturas y los filtros se resuelven en la API sumando filas.
- Clave DynamoDB propuesta: pk `data_type#nivel#periodo` (p. ej. `alert#day#2026-10-01`), sk = combinación de dimensiones; medidas como listas de 24 casillas.

#### Trazas
Los mismos campos, con los mismos nombres, van como atributos de los spans, para filtrar trazas y agregados igual. Salvedades:
- En la traza va el **rango** de monto, no el monto exacto. Nunca `customer_id`.
- `mark` y `resolution_time` van en el span de la resolución, y cada corrección de `fraud_` en su propio span, porque la traza original ya se cerró.
- En métricas técnicas (Prometheus) sólo se usan como dimensiones los campos con pocos valores posibles.

#### API y UI
- `GET /metrics/overview` y `GET /metrics/agent` (`from`, `to`, filtros), permisos `dashboard`/`monitor`; un use case por endpoint sobre un puerto `MetricsRollupRepository`.
- El embudo "Tiempo real" (en cola, en proceso) **no** es un agregado: son contadores de estado actual que suben y bajan, en una entidad aparte.
- `/dashboard` y `/monitor` dejan los mocks. Los KPIs sin fuente (alucinaciones, disponibilidad) se muestran "sin datos". `/historico-fraude` lee alertas cerradas reales (paginado por fecha).

### Fase D — Monitores (reglas de alerta en Grafana/Alertmanager, fuera de la app)
| Monitor | Condición sugerida |
| --- | --- |
| Workflow fallando | tasa de `FAILED` > 5 % en 15 min |
| LLM caído o lento | error rate LLM > 10 % en 5 min, o p95 > 30 s |
| SLA en riesgo | p95 de duración de workflow > 5 min |
| Cola de analistas atascada | alertas `ESCALATED` sin tomar > 15 min |
| Sin capacidad | slots voicebot = 0 o analistas disponibles = 0 durante 10 min en horario operativo |
| Dead man's switch | 0 alertas procesadas en 30 min con el agente ON |
| Investigación degradada | fallos de Vector Store > 20 % en 15 min |

## 5. Decisiones

Tomadas el 2026-10-01:
- Los KPIs técnicos derivables de datos de dominio también van a la app.
- Niveles día (90 d) / mes / año, todos con perfil por hora del día; sólo medidas acumulativas, y el frontend lo indica.
- Datos tardíos por maduración del fraude (4 días / 6 meses): bucket por fecha de la alerta + deltas a todos los niveles vivos.
- `mark` = decisión inmediata e inmutable de ARIA, analista o voicebot; `fraud_` = realidad del caso, nace igual a `mark` y la corrige el equipo de fraude hasta 6 meses después. No hay un tercer campo.
- Timestamps para medir maduración: `marked_at` (decisión) y `fraud_reviewed_at` (última revisión del equipo de fraude, aunque confirme el valor).
- Rangos de monto configurables en la configuración inmediata, congelados por alerta.
- Zona horaria de Bogotá: aplicada ya en todos los deployments del proyecto (`TZ` en las imágenes y en los configmaps de OKD, `OPERATIONS_TIMEZONE` explícito, Celery con `timezone=OPERATIONS_TIMEZONE` y mensajes en UTC).

Pendientes:
1. **Orden de fases**: recomendado A → C → B → D.
2. **OKD**: ¿Collector propio en el namespace o uno corporativo? Lo decide plataforma.
3. **Alucinaciones / uso correcto de datos**: ¿evaluador (LLM-judge muestreado) o se quitan de `/monitor` por ahora?
4. **Ingreso de las correcciones de `fraud_` en producción**: ¿por qué canal llegan a ARIA (API desde el sistema del equipo de fraude, carga CSV periódica, edición en la UI de ARIA)?
