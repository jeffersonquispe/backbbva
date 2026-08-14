# Changelog

Historial de cambios funcionales del sistema ARIA. Formato libre, en español,
agrupado por fecha de sesión de trabajo — no sigue estrictamente Keep a
Changelog porque el proyecto es un PoC de evolución rápida, pero cada entrada
dice qué cambió, por qué, y qué archivos toca para poder rastrearlo en el código.

## 2026-08-14

### Costeo de experimentos (tokens + precio en USD)

- **Nuevo `pricing.yaml`**: tarifario editable (USD por 1M tokens, input/output)
  por modelo Bedrock. A diferencia de `aria_rules.yaml`, este archivo SÍ se lee
  en tiempo de ejecución.
- **Nuevo `pricing.py`**: carga el tarifario y calcula costo por agente y total
  a partir de `input_tokens`/`output_tokens`.
- `scripts/run_pilot_alerts_por_gt.py`: cada experimento (`summary.json`) ahora
  guarda `model_id`, `costo_total_usd` y `costo_por_agente_usd` junto a los
  tokens; se imprime en consola al terminar la corrida.
- `app/app.py` (tab "Piloto Blind Test"): KPI de costo total + costo por agente
  junto al de tokens.
- `requirements.txt` / `requirements-app.txt`: agregado `PyYAML`.

### `razon_marcacion` deja de ocultarse del pipeline

- Antes se retiraba del payload como "leak de GT" (`GT_LEAK_FIELDS`). Ahora
  viaja hasta Clasificador y Analista como **contexto adicional no vinculante**
  — pueden verla, no están obligados a que su decisión coincida con ella.
- Archivos: `scripts/run_pilot_alerts_por_gt.py`, `app/app.py` (ambos
  `GT_LEAK_FIELDS` actualizados), `agents/clasificador.py`, `agents/analista.py`
  (nueva regla en cada `SYSTEM_PROMPT`), `aria_rules.yaml` (RULE-CLA-03,
  RULE-ANA-04). `eventid` / `marcacion_final` / `tipo` siguen ocultos (alias
  directo del ground truth).

### Métricas de accuracy separadas por agente

- Antes solo se medía accuracy del Ejecutor (marcación oficial) contra el GT.
  Ahora `scripts/run_pilot_alerts_por_gt.py` calcula accuracy + matriz de
  confusión **por separado** para Clasificador, Analista y Ejecutor
  (`metricas_por_agente` en `summary.json`), cada uno comparado contra el mismo
  GT de 3 clases.
- `app/app.py`: sección "Accuracy por agente" con 3 tiles comparables.

### Clasificador: pasa de clasificar taxonomía FCP a decidir riesgo directamente

Cambio de arquitectura, no solo de prompt: antes el Clasificador elegía 1 de 10
taxonomías FCP cerradas (RULE-CLA-01 original) y esa taxonomía se traducía a
RISK/NO_RISK/RISK_SUSPECTED en otro lado. Ahora **decide `marcacion_aric`
directamente** (Literal de 3 valores forzado por schema, igual que ya hacía el
Ejecutor) y el catálogo FCP pasa a ser solo conocimiento de referencia en el
prompt. El Analista queda como el **único** agente que asigna la taxonomía FCP
definitiva.

- **Nuevo `agents/_taxonomia.py`**: catálogo de las 10 taxonomías FCP + tipo
  `Literal` cerrado, separado de `clasificador.py` porque ahora es conocimiento
  compartido (el Analista lo sigue necesitando como su tipo de salida).
- **Nuevo `agents/_marcacion.py`**: `derivar_marcacion_aric()` — la regla de
  prefijo FR___/NF___ + escalamiento, sacada de `agents/analista.py` a un
  módulo compartido para evitar un import circular (`analista.py` ya importaba
  de `clasificador.py`).
- `agents/clasificador.py`: schema nuevo (`marcacion_aric` en vez de
  `clasificacion`), fallback cambiado de `NF___FALSO_POSITIVO` (permisivo) a
  `RISK_SUSPECTED` (conservador, consistente con el resto del pipeline).
- `agents/analista.py`: ahora asigna la taxonomía FCP desde cero (antes
  "confirmaba o rectificaba" la del Clasificador); su prompt ya no recibe una
  taxonomía inicial, recibe el triage de riesgo del Clasificador.
- `schemas.py`, `agents/documentador.py`: adaptados al nuevo `ClasificadorOutput`.
- Ripple fix en todos los consumidores de `clasificador.clasificacion`:
  `scripts/run_pilot_alerts_por_gt.py`, `app/app.py` (simulador en vivo +
  dashboard), `scripts/eval_no_gt.py`, `app/streamlit_dashboard.py`,
  `scripts/test_local_lambda.py`.
- `aria_rules.yaml`: RULE-CLA-01 y RULE-CLA-04 reescritas, RULE-ANA-01 actualizada.

### Motor de decisión de fraude BBVA (reglas duras + catálogo de Modus Operandi)

Basado en la matriz de decisión real de un analista humano de monitoreo de
fraude (ARIC / Biocatch / Veridas / 3270): reglas duras determinísticas antes
del LLM, catálogo de MO con señales y acciones de contención por taxonomía, y
observación estandarizada para ARIC.

- **Nuevo `agents/_modus_operandi.py`**:
  - `MODUS_OPERANDI_POR_TAXONOMIA`: señales típicas + acciones de contención
    por cada una de las 10 taxonomías FCP (Suplantación, SIM Swap, Vishing,
    RAT/Malware, Pharming, Pérdida/Robo de tarjeta, etc.).
  - `evaluar_reglas_duras(alert)`: filtros previos **determinísticos**, sin
    LLM — Wealth/VIP (deriva a banca privada, sin bloqueo automático),
    `biocatch_indrobo1` (hurto → RISK), `isRat`/`isMobileRat`/`isBot`
    (malware → RISK). Si dispara, el caso es inequívoco y no paga 3 llamadas
    a Bedrock ni se arriesga a que el LLM lo interprete distinto en cada corrida.
  - `formatear_observacion_aric()`: línea estandarizada
    `[MO: ...] [CANAL: ...] [HABITO: SI/NO/N-D] [DISP: HABITUAL/NUEVO/N-D] - texto`.
- `lambda_function.py` (modo `"pipeline"`): si `evaluar_reglas_duras()` dispara,
  se construyen las salidas de Clasificador/Analista/Ejecutor directo del
  veredicto (**0 tokens, 0 costo, 0 segundos**) — Perfilador y Documentador
  siguen corriendo igual, para no perder narrativa ni cierre. Nuevo campo
  `regla_dura_aplicada` en la respuesta del pipeline.
- `agents/clasificador.py`, `agents/analista.py`, `agents/ejecutor.py`: el
  catálogo MO se inyecta como contexto de referencia en los 3 `SYSTEM_PROMPT`
  (antes solo el Clasificador tenía la lista corta de taxonomías).
- `schemas.py`: `AlertInput.segmento` (nuevo, opcional — no viene en el dataset
  sintético actual, queda listo para cuando se integre 3270 PE55);
  `AnalistaOutput.modus_operandi`; `EjecutorOutput.acciones_sugeridas` +
  `EjecutorOutput.observacion_aric`.
- `app/app.py` (simulador en vivo): tarjetas de Analista y Ejecutor muestran
  MO, bloqueos sugeridos y la observación ARIC.
- `aria_rules.yaml`: nuevas secciones `reglas_duras_previas` (RULE-DURA-01/02/03)
  y `catalogo_modus_operandi`; nueva RULE-EJE-04.

**Validado con Bedrock real**: caso con `isMobileRat=1` disparó
`MALWARE_RAT_BOT` correctamente — Clasificador/Analista/Ejecutor en 0.0s / 0
tokens, `modus_operandi="Malware / RAT APK"`, acciones y observación ARIC bien
formadas, Documentador generó el cierre igual.

**Incidente corregido en el camino:** `aria_rules.yaml` se corrompió durante
una edición previa (el texto de un mensaje largo del usuario terminó
duplicado dentro del valor de `system_name`) y quedó sin detectar hasta
revisar el archivo para esta tarea. Restaurado a partir de `git diff` contra
el último commit limpio, conservando las reglas legítimas ya agregadas en la
sesión.

**Bug encontrado y corregido durante el smoke test:** `lambda_function.py`
tenía imports locales (`from schemas import ClasificadorOutput` /
`AnalistaOutput`) dentro de los modos standalone `"analista"`/`"ejecutor"`.
Al agregar los mismos imports a nivel de módulo para el bypass de reglas
duras, Python empezó a tratar esos nombres como variables locales de **toda**
la función `lambda_handler` (regla de scoping de Python: un nombre asignado
en cualquier rama de una función es local a toda la función), rompiendo el
modo `"pipeline"` con `UnboundLocalError`. Se eliminaron los imports locales
redundantes.
