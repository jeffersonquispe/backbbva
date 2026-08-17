"""
Dashboard de Evaluación SIN Ground Truth de los Agentes ARIA (HU-2.5.1, ajustada).
Visualiza los resultados generados por `eval_no_gt.py` (archivo `eval_results.json`).

Ejecutar con:
    streamlit run app/streamlit_dashboard.py
"""

import json
import os
import pandas as pd
import altair as alt
import streamlit as st

RESULTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output", "eval_results.json")

st.set_page_config(page_title="ARIA · Evaluación sin GT", page_icon="🛡️", layout="wide")

PALETTE = {
    "nuevo": "#1F8F6E",
    "modificado": "#A6720B",
    "pendiente": "#6E5B9E",
    "accent": "#24507F",
    "danger": "#B0402E",
    "muted": "#6B7686",
}


@st.cache_data
def load_results(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


data = load_results(RESULTS_PATH)

st.title("🛡️ ARIA — Evaluación de línea base sin Ground Truth")
st.caption(
    "Pipeline evaluado: **Perfilador → Clasificador → Analista** "
    "(Ejecutor y Documentador fuera de alcance — ver `docs/HU-Perfilamiento.md`)."
)

if data is None:
    st.error(
        "No se encontró `eval_results.json`. Genera resultados primero con:\n\n"
        "```\npython scripts/eval_no_gt.py\n```"
    )
    st.stop()

summary = data["summary"]
cases = data["cases"]
n = summary.get("total_casos", 0)

with st.expander("¿Por qué sin Ground Truth?", expanded=False):
    st.markdown(
        "La hoja **'Muestra'** del Excel de origen solo tiene **5 registros reales** "
        "con datos (el resto son celdas vacías con formato heredado), y el campo "
        "que podría servir de referencia (`marcacion_final` / `riskreasons`) mezcla "
        "decisiones evaluadas por un analista con cierres automáticos por SLA vencido "
        "(`[Auto-Close Bulk Purge 72h]`). Por eso esta evaluación no calcula "
        "precisión/recall contra una etiqueta \"verdadera\": mide señales de calidad "
        "del **proceso** (acuerdo entre agentes, escalamiento, fallback, latencia) que "
        "no requieren GT humano — salvo la detección de *Cold Start*, que sí tiene una "
        "regla determinística verificable."
    )

st.caption(f"Generado: `{data.get('generated_at', '—')}` · {n} caso(s) evaluado(s) sobre datos reales.")

if n < 10:
    st.warning(
        f"⚠️ Muestra de solo **{n} casos**. Este es un piloto / smoke-test del pipeline, "
        "no una línea base estadísticamente significativa (HU-2.5.1)."
    )

# --- Hallazgo destacado: taxonomía del Analista fuera del conjunto cerrado ---
tasa_invalida = summary.get("tasa_analista_taxonomia_invalida", 0)
if tasa_invalida > 0:
    st.error(
        f"🔴 **Hallazgo:** en **{tasa_invalida:.0%}** de los casos, `clasificacion_final` "
        "del Analista **no pertenece** al conjunto cerrado de taxonomías FCP "
        "(ej. `FR___ACCOUNT_TAKEOVER`, `FR___ATO_ACCOUNT_TAKEOVER` en vez de "
        "`[FR___SUPLANTACIN]`). A diferencia del Clasificador, `AnalistaAgent` no valida "
        "ni remapea su salida contra `TAXONOMIAS_PERMITIDAS` — esto contamina la "
        "clasificación que llegaría a Ejecutor/Documentador. Recomendación: aplicar la "
        "misma validación de conjunto cerrado usada en `clasificador.py` (líneas 82-85) "
        "también en `analista.py`."
    )

# --- KPIs ---
st.subheader("Indicadores de proceso (sin GT)")
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Casos evaluados", n)
k2.metric("Confirmación Analista", f"{summary.get('tasa_confirmacion_analista', 0):.0%}")
k3.metric("Escalamiento a humano", f"{summary.get('tasa_escalamiento', 0):.0%}")
k4.metric("Cold Start correcto", f"{summary.get('tasa_cold_start_correcto', 0):.0%}",
          help="Único punto con verdad objetiva: comparado contra AlertInput.is_cold_start() (regla determinística, no etiqueta humana).")
k5.metric("Taxonomía inválida (Analista)", f"{summary.get('tasa_analista_taxonomia_invalida', 0):.0%}",
          help="% de veces que 'clasificacion_final' del Analista cayó fuera del set cerrado FCP. Con LangChain + Literal debería ser 0%.")
k6.metric("Tasa de fallback", f"{summary.get('tasa_fallback', 0):.0%}",
          help="% de casos donde algún agente usó su fallback de error (Perfilador, Clasificador o Analista).")

st.divider()

# --- Métricas clásicas de clasificación (CON el GT limitado del dataset) ---
st.subheader("📐 Métricas clásicas de clasificación (con GT limitado)")
metrics_gt = data.get("metrics_con_gt")

if not metrics_gt or not metrics_gt.get("clasificador_vs_gt"):
    st.info("No hay casos con Ground Truth confiable en esta corrida para calcular precision/recall/F1.")
else:
    st.caption(f"**Target:** `{metrics_gt.get('target', 'marcacion_final')}` — la marcación de riesgo real "
               "de negocio (RISK / NO_RISK / RISK_SUSPECTED), no la taxonomía FCP fina.")
    st.warning(metrics_gt["advertencia"])
    if metrics_gt.get("casos_excluidos"):
        excluidos_txt = ", ".join(
            f"{c['customerid']} ({c['razon_marcacion_original']})" for c in metrics_gt["casos_excluidos"]
        )
        st.caption(f"Excluidos del cálculo por GT no evaluado: {excluidos_txt}")

    clas_m = metrics_gt["clasificador_vs_gt"]
    ana_m = metrics_gt["analista_vs_gt"]

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Accuracy Clasificador (triage)", f"{clas_m['accuracy']:.0%}",
              help="Marcación decidida directamente por el LLM del Clasificador en su triage rápido, sin el paso adversarial del Analista.")
    g2.metric("F1 macro Clasificador", f"{clas_m['macro_avg']['f1']:.2f}")
    g3.metric("Accuracy Analista (marcacion_aric)", f"{ana_m['accuracy']:.0%}",
              help="Marcación derivada determinísticamente en AnalistaAgent a partir de incertidumbre/escalamiento/prefijo — no vía LLM libre.")
    g4.metric("F1 macro Analista", f"{ana_m['macro_avg']['f1']:.2f}")
    st.caption(
        "`marcacion_aric` del Analista se deriva con una regla determinística "
        "(`_derivar_marcacion_aric` en `agents/analista.py`), no pidiéndole al LLM "
        "que elija entre 3 valores cerrados — la evaluación anterior mostró que eso "
        "falla el 80% de las veces con la taxonomía FCP."
    )

    def _tabla_por_clase(m, nombre):
        st.markdown(f"**{nombre}**")
        df = pd.DataFrame(m["per_class"])
        df = df.rename(columns={"clase": "Clase", "precision": "Precision", "recall": "Recall",
                                 "f1": "F1", "soporte": "Soporte"})
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(
            f"Macro avg — P: {m['macro_avg']['precision']:.2f} · R: {m['macro_avg']['recall']:.2f} "
            f"· F1: {m['macro_avg']['f1']:.2f}  |  Weighted avg F1: {m['weighted_avg']['f1']:.2f}"
        )

    def _matriz_confusion(m, nombre):
        labels = m["labels"]
        cm = m["confusion_matrix"]
        rows = []
        for i, real in enumerate(labels):
            for j, pred in enumerate(labels):
                rows.append({"Real (GT)": real, "Predicho": pred, "Casos": cm[i][j]})
        df_cm = pd.DataFrame(rows)
        base = alt.Chart(df_cm).encode(
            x=alt.X("Predicho:N", title="Predicho"),
            y=alt.Y("Real (GT):N", title="Real (GT)"),
        )
        heat = base.mark_rect().encode(
            color=alt.Color("Casos:Q", scale=alt.Scale(scheme="blues"), legend=None),
            tooltip=["Real (GT)", "Predicho", "Casos"],
        )
        text = base.mark_text(baseline="middle").encode(
            text="Casos:Q",
            color=alt.condition(alt.datum.Casos > (max(max(r) for r in cm) or 1) / 2,
                                 alt.value("white"), alt.value("black")),
        )
        st.altair_chart((heat + text).properties(height=220, title=f"Matriz de confusión — {nombre}"),
                         use_container_width=True)

    mc1, mc2 = st.columns(2)
    with mc1:
        _tabla_por_clase(clas_m, "Clasificador (triage) vs. GT")
        _matriz_confusion(clas_m, "Clasificador")
    with mc2:
        _tabla_por_clase(ana_m, "Analista (marcacion_aric) vs. GT")
        _matriz_confusion(ana_m, "Analista")

    if ana_m["accuracy"] > clas_m["accuracy"]:
        st.success(
            f"✅ El paso adversarial del Analista mejora la marcación de riesgo frente a "
            f"derivarla directo del Clasificador: {ana_m['accuracy']:.0%} vs. {clas_m['accuracy']:.0%} "
            "de accuracy (n muy pequeño — dirección, no magnitud, es lo interpretable aquí)."
        )

st.divider()

col_left, col_right = st.columns(2)

# --- Distribución de clasificación: inicial vs final ---
with col_left:
    st.subheader("Clasificación: Clasificador vs. veredicto del Analista")
    dist_inicial = summary.get("distribucion_triage_inicial", {})
    dist_final = summary.get("distribucion_clasificacion_final", {})
    rows = []
    for k, v in dist_inicial.items():
        rows.append({"clasificacion": k, "casos": v, "etapa": "Clasificador (inicial)"})
    for k, v in dist_final.items():
        rows.append({"clasificacion": k, "casos": v, "etapa": "Analista (final)"})
    df_dist = pd.DataFrame(rows)
    if not df_dist.empty:
        chart = (
            alt.Chart(df_dist)
            .mark_bar()
            .encode(
                y=alt.Y("clasificacion:N", sort="-x", title=None),
                x=alt.X("casos:Q", title="Casos", axis=alt.Axis(tickMinStep=1)),
                color=alt.Color(
                    "etapa:N",
                    title=None,
                    scale=alt.Scale(range=[PALETTE["accent"], PALETTE["modificado"]]),
                ),
                yOffset="etapa:N",
                tooltip=["etapa", "clasificacion", "casos"],
            )
            .properties(height=max(160, 34 * df_dist["clasificacion"].nunique()))
        )
        st.altair_chart(chart, use_container_width=True)
        st.caption(
            "Las categorías del Analista fuera de `[FR___...]`/`[NF___...]` no pertenecen "
            "al conjunto cerrado FCP (ver hallazgo arriba)."
        )
    else:
        st.info("Sin datos de clasificación.")

# --- Distribución de incertidumbre ---
with col_right:
    st.subheader("Nivel de incertidumbre del Analista")
    dist_inc = summary.get("distribucion_incertidumbre", {})
    order = ["BAJO", "MEDIO", "ALTO"]
    df_inc = pd.DataFrame(
        [{"nivel": k, "casos": v} for k, v in dist_inc.items()]
    )
    if not df_inc.empty:
        color_map = {"BAJO": PALETTE["nuevo"], "MEDIO": PALETTE["modificado"], "ALTO": PALETTE["danger"]}
        chart_inc = (
            alt.Chart(df_inc)
            .mark_bar()
            .encode(
                x=alt.X("nivel:N", sort=order, title=None),
                y=alt.Y("casos:Q", title="Casos", axis=alt.Axis(tickMinStep=1)),
                color=alt.Color(
                    "nivel:N",
                    legend=None,
                    scale=alt.Scale(domain=order, range=[color_map[k] for k in order]),
                ),
                tooltip=["nivel", "casos"],
            )
            .properties(height=280)
        )
        st.altair_chart(chart_inc, use_container_width=True)
    else:
        st.info("Sin datos de incertidumbre.")

st.divider()

# --- Latencia por etapa vs SLA ---
st.subheader("Latencia por etapa vs. SLA de negocio")
lat = summary.get("latencia_promedio_seg", {})
sla = summary.get("sla_objetivo_seg", 300)
df_lat = pd.DataFrame(
    [{"etapa": k.capitalize(), "segundos": v} for k, v in lat.items() if k != "total"]
)
c1, c2 = st.columns([2, 1])
with c1:
    if not df_lat.empty:
        chart_lat = (
            alt.Chart(df_lat)
            .mark_bar(color=PALETTE["accent"])
            .encode(
                x=alt.X("etapa:N", title=None, sort=["Perfilador", "Clasificador", "Analista"]),
                y=alt.Y("segundos:Q", title="Segundos (promedio)"),
                tooltip=["etapa", "segundos"],
            )
            .properties(height=260)
        )
        st.altair_chart(chart_lat, use_container_width=True)
with c2:
    st.metric("Total promedio / alerta", f"{lat.get('total', 0):.1f}s")
    st.metric("Máximo observado", f"{summary.get('latencia_maxima_seg', 0):.1f}s")
    st.metric("Cumplimiento SLA (<5 min)", f"{summary.get('sla_cumplido_pct', 0):.0%}")
    st.caption(
        "El Perfilador (LangChain + salida estructurada) concentra la mayor parte del "
        "tiempo — candidato a optimizar antes de sumar el vector store (HU-2.1.5)."
    )

st.divider()

# --- Distribución histórica de referencia (población, no GT) ---
st.subheader("Referencia poblacional: razones históricas reales")
st.caption(
    "Distribución real de `riskreasons_last` (hoja 'Servicio - razon'), excluyendo "
    "`[Auto-Close Bulk Purge 72h]` por no ser una decisión evaluada. Es un **contraste "
    "de contexto**, no una verdad de referencia por caso."
)
ref_dist = data.get("reference_distribution_riskreasons", {})
if ref_dist:
    df_ref = pd.DataFrame(
        [{"razon": k, "proporcion": v} for k, v in list(ref_dist.items())[:10]]
    )
    chart_ref = (
        alt.Chart(df_ref)
        .mark_bar(color=PALETTE["muted"])
        .encode(
            y=alt.Y("razon:N", sort="-x", title=None),
            x=alt.X("proporcion:Q", title="Proporción histórica", axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("proporcion:Q", format=".1%"), "razon"],
        )
        .properties(height=300)
    )
    st.altair_chart(chart_ref, use_container_width=True)

st.divider()

# --- Detalle por caso ---
st.subheader("Detalle por caso")
for c in cases:
    clas = c["clasificador"]
    ana = c["analista"]
    perf = c["perfilamiento"]
    badge = "🔴" if not ana["confirmado"] else "🟢"
    invalid_tag = " · ⚠️ taxonomía fuera del set cerrado" if not c["analista_taxonomia_valida"] else ""
    with st.expander(
        f"{badge} Cliente {c['customerid']} — {clas['marcacion_aric']} → {ana['clasificacion_final']}"
        f" (incertidumbre {ana['nivel_incertidumbre']}){invalid_tag}"
    ):
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown(f"**Canal / servicio:** `{c['channel']}` · `{c['integrationpoint']}`")
            st.markdown(f"**Monto:** ${c['amount_value']:,.2f} COP")
            st.markdown(f"**Cold Start:** real=`{c['cold_start_real']}` · LLM=`{c['cold_start_llm']}` "
                        f"· {'✅ coincide' if c['cold_start_match'] else '❌ no coincide'}")
            st.markdown(f"**Tiempos:** perfilador {c['tiempos']['perfilador']}s · "
                        f"clasificador {c['tiempos']['clasificador']}s · analista {c['tiempos']['analista']}s")
        with cc2:
            st.markdown(f"**Clasificador (triage):** `{clas['marcacion_aric']}`")
            st.markdown(f"**Analista confirma:** `{ana['confirmado']}` → final `{ana['clasificacion_final']}`")
            st.markdown(f"**Escalamiento:** `{ana['requiere_escalamiento']}` — {ana.get('razon_escalamiento') or '—'}")

        st.markdown("**Texto consolidado del Perfilamiento**")
        st.text(perf["texto_consolidado"])

        st.markdown("**Justificación del Clasificador**")
        st.text(clas["cot_justificacion"])

        st.markdown("**Hipótesis refutadora del Analista**")
        st.text(ana["hipotesis_refutadora"])
        if ana.get("evidencia"):
            st.markdown("**Evidencia:**")
            for ev in ana["evidencia"]:
                st.markdown(f"- {ev}")

st.divider()
st.caption(
    "Generar de nuevo: `python eval_no_gt.py` · Roadmap pendiente: vector store (HU-2.1.5–2.1.7), "
    "feedback loop del Analista (HU-2.2.6), baseline ampliado (HU-2.5.x) — ver docs/HU-Perfilamiento.md"
)
