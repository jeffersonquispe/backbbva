"""
App Web Streamlit — Sistema Multiagente ARIA (BBVA Prevención de Fraude).
Permite simular el pipeline en vivo, visualizar la consola de analista (HITL) y monitorear SLAs.
"""

import sys
import os
import json
import time
import html

sys.stdout.reconfigure(encoding='utf-8')

import streamlit as st
import pandas as pd

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT_DIR)

from dotenv_util import parse_dotenv

parse_dotenv(os.path.join(_ROOT_DIR, '.env'))

def safe_float(val, default=0.0):
    if val is None or val == "":
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def esc(val, default=""):
    """Escapa texto libre (salida del LLM o campos crudos de la alerta) antes de
    interpolarlo en bloques HTML con unsafe_allow_html=True. Sin esto, un dato
    de alerta bajo control de un atacante (ej. nombre_razon_social en un caso
    de toma de cuenta) que el LLM reproduzca en su razonamiento se renderizaría
    como HTML/JS crudo en la consola del analista."""
    if val is None:
        return default
    return html.escape(str(val))


def kpi_color(value, good=0.7, warn=0.4, invert=False):
    """Verde/ambar/rojo segun umbral. invert=True para metricas donde MENOS es mejor (ej. tasa de fallback)."""
    if value is None:
        return "#8FA6BF"
    if invert:
        if value <= warn:
            return "#00E676"
        if value <= good:
            return "#FF9100"
        return "#FF4D4D"
    if value >= good:
        return "#00E676"
    if value >= warn:
        return "#FF9100"
    return "#FF4D4D"


def kpi_tile(label, value_str, color, sub=None):
    sub_html = f'<div class="kpi-sub">{esc(sub)}</div>' if sub else ""
    st.markdown(
        f"""<div class="kpi-tile">
            <div class="kpi-label">{esc(label)}</div>
            <div class="kpi-value" style="color:{color}">{esc(value_str)}</div>
            {sub_html}
        </div>""",
        unsafe_allow_html=True,
    )


def style_confusion_matrix(cm, labels):
    """Heatmap simple: verde en la diagonal (aciertos), rojo fuera de ella (errores),
    intensidad proporcional al valor de cada celda."""
    df_cm = pd.DataFrame(cm, index=[f"Real: {l}" for l in labels], columns=[f"Pred: {l}" for l in labels])
    n = len(labels)
    max_correct = max((cm[i][i] for i in range(n)), default=0) or 1
    max_error = max((cm[i][j] for i in range(n) for j in range(n) if i != j), default=0) or 1

    def _apply(_df):
        styles = pd.DataFrame("", index=df_cm.index, columns=df_cm.columns)
        for i in range(n):
            for j in range(n):
                val = cm[i][j]
                if i == j:
                    alpha = 0.10 + 0.55 * (val / max_correct) if val else 0.04
                    styles.iloc[i, j] = f"background-color: rgba(0,230,118,{alpha:.2f}); font-weight: 700;"
                else:
                    alpha = 0.08 + 0.55 * (val / max_error) if val else 0.0
                    styles.iloc[i, j] = f"background-color: rgba(255,77,77,{alpha:.2f});"
        return styles

    return df_cm.style.apply(_apply, axis=None)


from lambda_function import lambda_handler
from schemas import AlertInput
from pricing import calcular_costos_por_agente

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA Y ESTILOS CSS BBVA
# ==============================================================================
st.set_page_config(
    page_title="ARIA — Prevención de Fraude BBVA",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    /* Fondo Oscuro Elegante BBVA */
    .stApp {
        background-color: #060E1A;
        color: #E2E8F0;
    }
    
    /* Header Principal */
    .header-box {
        background: linear-gradient(135deg, #004481 0%, #1464A5 50%, #002B49 100%);
        padding: 24px;
        border-radius: 16px;
        box-shadow: 0 8px 32px rgba(0, 68, 129, 0.3);
        margin-bottom: 24px;
        border: 1px solid rgba(255, 255, 255, 0.1);
    }
    
    .header-title {
        color: #FFFFFF;
        font-size: 28px;
        font-weight: 700;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 12px;
    }
    
    .header-subtitle {
        color: #B2D4F5;
        font-size: 14px;
        margin-top: 6px;
    }
    
    /* Tarjetas de Agente Glassmorphism */
    .agent-card {
        background: rgba(18, 35, 61, 0.7);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(45, 204, 205, 0.2);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    
    .agent-card:hover {
        border-color: #00E5FF;
        transform: translateY(-2px);
    }
    
    .agent-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        padding-bottom: 8px;
    }
    
    .agent-name {
        font-size: 18px;
        font-weight: 600;
        color: #00E5FF;
    }
    
    /* Badges de Estado */
    .badge-risk {
        background-color: rgba(255, 77, 77, 0.2);
        color: #FF4D4D;
        border: 1px solid #FF4D4D;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 13px;
    }
    
    .badge-norisk {
        background-color: rgba(0, 230, 118, 0.2);
        color: #00E676;
        border: 1px solid #00E676;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 13px;
    }
    
    .badge-suspected {
        background-color: rgba(255, 145, 0, 0.2);
        color: #FF9100;
        border: 1px solid #FF9100;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 13px;
    }

    .voicebot-box {
        background: linear-gradient(135deg, rgba(255, 145, 0, 0.15) 0%, rgba(255, 77, 77, 0.15) 100%);
        border: 1px solid #FF9100;
        border-radius: 8px;
        padding: 12px 16px;
        margin-top: 12px;
    }

    /* Bloques Input/Output dentro de cada tarjeta de agente */
    .io-label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #6E85A3;
        font-weight: 700;
        margin-top: 10px;
        margin-bottom: 4px;
    }

    .io-box {
        background: rgba(255, 255, 255, 0.03);
        border-left: 3px solid #3A4A5E;
        padding: 8px 12px;
        border-radius: 4px;
        font-size: 13px;
        margin-bottom: 6px;
    }

    .io-box.output {
        border-left-color: #00E5FF;
    }

    /* Banner de veredicto final (tipología + marcación) */
    .verdict-box {
        border: 2px solid #00E5FF;
        background: rgba(0, 229, 255, 0.08);
        display: flex;
        justify-content: space-around;
        align-items: center;
        text-align: center;
        flex-wrap: wrap;
        gap: 16px;
    }

    .verdict-label {
        font-size: 12px;
        color: #8FA6BF;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 4px;
    }

    .verdict-value {
        font-size: 22px;
        font-weight: 700;
        color: #00E5FF;
    }

    .verdict-arrow {
        font-size: 26px;
        color: #3A4A5E;
    }

    /* Tiles de KPI con color segun umbral (accuracy, fallback, SLA, etc.) */
    .kpi-tile {
        background: rgba(18, 35, 61, 0.7);
        border: 1px solid rgba(45, 204, 205, 0.2);
        border-radius: 10px;
        padding: 12px 16px;
        text-align: left;
    }
    .kpi-label {
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #8FA6BF;
        margin-bottom: 4px;
    }
    .kpi-value {
        font-size: 24px;
        font-weight: 700;
        line-height: 1.1;
    }
    .kpi-sub {
        font-size: 11px;
        color: #6E85A3;
        margin-top: 4px;
    }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ==============================================================================
# CARGAR MUESTRAS DESDE Muestra_200_ARIA_alerts_por_gt.json
# ==============================================================================
ALERTS_JSON_PATH = os.path.join(_ROOT_DIR, 'Muestra_200_ARIA_alerts_por_gt.json')
GT_GROUP_LABELS = {"risk": "🔴 RISK", "no-risk": "🟢 NO_RISK", "risk-suspected": "🟠 RISK_SUSPECTED"}

# Campos que sólo existen para trazabilidad/etiquetado del dataset y filtran la
# respuesta esperada si se dejan en el payload que ve el pipeline — ARIA ya los
# trata como tal en el flujo blind test de este mismo archivo (ver blind_data.pop
# más abajo). `tipo` en particular es casi un alias de marcacion_final (Fraude/
# NoFraude coincide con el GT en 195/200 casos del dataset balanceado).
# razon_marcacion NO está acá: Clasificador y Analista sí pueden verla como
# contexto adicional (no es obligatorio basarse en ella para clasificar).
GT_LEAK_FIELDS = ("eventid", "marcacion_final", "tipo")


@st.cache_data
def load_alert_groups():
    if not os.path.exists(ALERTS_JSON_PATH):
        return {}
    with open(ALERTS_JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

# ==============================================================================
# HEADER DE LA APLICACIÓN
# ==============================================================================
st.markdown("""
<div class="header-box">
    <div class="header-title">
        🛡️ ARIA — Agente de Prevención de Fraude (BBVA Colombia)
    </div>
    <div class="header-subtitle">
        Plataforma Multiagente de IA en AWS Lambda & Amazon Bedrock (Claude Sonnet 4.6)
    </div>
</div>
""", unsafe_allow_html=True)

# Cargar muestras
alert_groups = load_alert_groups()

# ==============================================================================
# NAVEGACIÓN PRINCIPAL
# ==============================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "⚡ Simulador de Alertas en Vivo",
    "🚨 Consola Analista (Human-in-the-Loop)",
    "📊 Dashboard de Métricas & SLAs",
    "🧪 Piloto Blind Test (200 muestras)"
])

# ------------------------------------------------------------------------------
# TAB 1: SIMULADOR DE ALERTAS EN VIVO
# ------------------------------------------------------------------------------
with tab1:
    st.subheader("🧪 Simulación de Invocación del Pipeline Agéntico")
    
    col_sel, col_info = st.columns([1, 2])
    
    with col_sel:
        st.markdown("##### 1. Selección de Alerta de Entrada")
        available_groups = [g for g in ("risk", "no-risk", "risk-suspected") if alert_groups.get(g)]

        if available_groups:
            selected_group = st.selectbox(
                "Grupo GT (oculto al pipeline — sólo para armar el blind test):",
                available_groups,
                format_func=lambda g: f"{GT_GROUP_LABELS.get(g, g)} ({len(alert_groups[g])} casos)",
            )
            group_samples = alert_groups[selected_group]
            options = [
                f"Caso #{i+1} — Customer: {str(s.get('customerid')).split('.')[0]} (${safe_float(s.get('amount_value')):,.0f} COP)"
                for i, s in enumerate(group_samples)
            ]
            selected_idx = st.selectbox("Selecciona una alerta sintética:", range(len(options)), format_func=lambda x: options[x])
            sel_data = group_samples[selected_idx].copy()
            # eventid/marcacion_final/tipo son metadata de dataset o correlato
            # directo del GT (ver GT_LEAK_FIELDS) — fuera de la vista UI para que
            # el "veredicto" mostrado abajo sea comparable, no una copia.
            # razon_marcacion sí queda visible: Clasificador/Analista pueden usarla.
            for f in GT_LEAK_FIELDS:
                sel_data.pop(f, None)
        else:
            st.warning(f"No se encontró `{os.path.basename(ALERTS_JSON_PATH)}`. Usando caso sintético de respaldo.")
            selected_group = None
            sel_data = {
                "customerid": "8614703",
                "eventtype": "paymentRT",
                "channel": "GL",
                "integrationpoint": "SMGG20210247 - postIdentityDocumentTransfers",
                "biocatch_score": 930.0,
                "Model_score": 84465.0,
                "amount_value": 3000000.0,
                "fecha_transaccion": "2026-07-10 11:32:46.000",
                "biocatch_isMobileRat": 0,
                "biocatch_isEmulator": 0,
                "biocatch_isRat": 0,
                "biocatch_isBot": 0,
                "MontoMasAltoGlomo": 10000000.0,
                "MontoMasAltoBreB": 10000000.0
            }
            
        btn_run = st.button("🚀 EJECUTAR PIPELINE MULTIAGENTE ARIA", type="primary", use_container_width=True)

    with col_info:
        st.markdown("##### 📄 Atributos de la Alerta Seleccionada (`AlertInput`)")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Customer ID", str(sel_data.get('customerid', 'N/A')).split('.')[0])
        c2.metric("Monto Transacción", f"${safe_float(sel_data.get('amount_value')):,.0f} COP")
        c3.metric("Canal / Tipo", f"{sel_data.get('channel')} | {sel_data.get('eventtype')}")
        c4.metric("Microservicio", str(sel_data.get('integrationpoint', '')).split(' - ')[0])


        with st.expander("🔍 Ver payload completo (43 campos sintéticos)", expanded=False):
            st.json(sel_data)

    st.markdown("---")

    if btn_run:
        st.markdown("### 🏃‍♂️ Ejecución en Tiempo Real de los 5 Agentes ARIA")
        
        progress_bar = st.progress(0)
        status_text = st.empty()

        # Eliminar cualquier rastro del Ground Truth para un verdadero Blind Test.
        # razon_marcacion se conserva: es contexto válido para Clasificador/Analista,
        # no un alias directo del veredicto como marcacion_final/tipo.
        blind_data = sel_data.copy()
        blind_data.pop("marcacion_final", None)
        blind_data.pop("tipo", None)
        
        # Invocación del Pipeline
        event_payload = {"mode": "pipeline", "alert": blind_data}
        
        status_text.text("⚡ Invocando AWS Lambda con Claude Sonnet 4.6 en Bedrock...")
        progress_bar.progress(25)

        start_time = time.time()
        response = lambda_handler(event_payload)
        total_time = time.time() - start_time
        
        progress_bar.progress(100)
        status_text.text(f"✅ Pipeline finalizado en {total_time:.3f} segundos.")

        if response["statusCode"] == 200:
            res_body = json.loads(response["body"])

            perf = res_body.get("perfilamiento", {})
            clas = res_body.get("clasificador", {})
            ana = res_body.get("analista", {})
            eje = res_body.get("ejecutor", {})
            doc = res_body.get("documentador", {})

            # --- BANNER DE VEREDICTO FINAL: Tipología de Fraude + Marcación ARIC ---
            tipologia_final = ana.get('clasificacion_final', 'N/A')
            marcacion_final = eje.get('marcacion_aric', 'N/A')
            marc_badge_class = ("badge-risk" if marcacion_final == "RISK"
                                 else "badge-norisk" if marcacion_final == "NO_RISK"
                                 else "badge-suspected")

            st.markdown(f"""
            <div class="agent-card verdict-box">
                <div>
                    <div class="verdict-label">🏷️ Tipología de Fraude (Clasificación Final)</div>
                    <div class="verdict-value">{esc(tipologia_final)}</div>
                </div>
                <div class="verdict-arrow">→</div>
                <div>
                    <div class="verdict-label">🛡️ Marcación ARIC Final</div>
                    <span class="{marc_badge_class}" style="font-size:20px; padding:8px 20px;">{esc(marcacion_final)}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

            if selected_group:
                gt_normalizado = selected_group.strip().upper().replace("-", "_")
                if marcacion_final == gt_normalizado:
                    st.success(f"✅ Coincide con el GT del grupo seleccionado (`{gt_normalizado}`).")
                else:
                    st.error(f"❌ No coincide con el GT del grupo seleccionado — esperado `{gt_normalizado}`, predicho `{marcacion_final}`.")

            # --- AGENTE 0: PERFILADOR (se ejecuta primero, evidencia de entrada para Clasificador/Analista) ---
            st.markdown(f"""
            <div class="agent-card">
                <div class="agent-header">
                    <div class="agent-name">🧭 0. Agente de Perfilamiento (HU-2.0.x)</div>
                    <span class="badge-suspected">LangChain · ChatBedrock</span>
                </div>
                <div class="io-label">📥 Input (alerta cruda)</div>
                <div class="io-box">
                    Customer: <b>{esc(blind_data.get('customerid'))}</b> | Canal: {esc(blind_data.get('channel'))} | Evento: {esc(blind_data.get('eventtype'))}<br/>
                    Servicio: {esc(blind_data.get('integrationpoint'))}<br/>
                    Monto: ${safe_float(blind_data.get('amount_value')):,.0f} COP | Biocatch: {esc(blind_data.get('biocatch_score'))} | Featurespace: {esc(blind_data.get('Model_score'))}
                </div>
                <div class="io-label">📤 Output</div>
                <div class="io-box output">
                    <p><b>Perfil de Usuario:</b> {esc(perf.get('perfil_usuario'))}</p>
                    <p><b>Perfil de Transacción:</b> {esc(perf.get('perfil_transaccion'))}</p>
                    <p><b>Perfil Histórico:</b> {esc(perf.get('perfil_historico'))}</p>
                    <p><b>Hipótesis de Sospecha:</b> <i>{esc(perf.get('hipotesis_sospecha'))}</i></p>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # --- MESH DE LOS 4 AGENTES SIGUIENTES ---
            col_a1, col_a2 = st.columns(2)

            with col_a1:
                # 1. CLASIFICADOR
                marcacion_clas = clas.get('marcacion_aric', 'N/A')
                clas_badge_class = ("badge-risk" if marcacion_clas == "RISK"
                                     else "badge-norisk" if marcacion_clas == "NO_RISK"
                                     else "badge-suspected")

                st.markdown(f"""
                <div class="agent-card">
                    <div class="agent-header">
                        <div class="agent-name">⏱️ 1. Agente Clasificador (HU-2.1.x)</div>
                        <span class="{clas_badge_class}">ARIC: {marcacion_clas}</span>
                    </div>
                    <div class="io-label">📥 Input</div>
                    <div class="io-box">
                        Perfil de Transacción: <i>"{esc(perf.get('perfil_transaccion'))}"</i><br/>
                        Hipótesis de Sospecha: <i>"{esc(perf.get('hipotesis_sospecha'))}"</i>
                    </div>
                    <div class="io-label">📤 Output — Triage de Riesgo (RISK/NO_RISK/RISK_SUSPECTED)</div>
                    <div class="io-box output">
                        <p><b>Marcación:</b> <span class="{clas_badge_class}">{esc(marcacion_clas)}</span></p>
                        <p><b>Justificación CoT:</b> {esc(clas.get('cot_justificacion'))}</p>
                        <p><small><b>Cold Start Aplicado:</b> {clas.get('regla_cold_start_aplicada')}</small></p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # 3. EJECUTOR
                marcacion = eje.get('marcacion_aric', 'RISK_SUSPECTED')
                badge_class = "badge-risk" if marcacion == "RISK" else ("badge-norisk" if marcacion == "NO_RISK" else "badge-suspected")

                vb_html = ""
                if eje.get('disparar_voicebot'):
                    vb_html = f"""
                    <div class="voicebot-box">
                        📞 <b>DISPARAR VOICEBOT INDRA: ACTIVADO</b><br/>
                        <small><b>Motivo:</b> {esc(eje.get('motivo_voicebot'))}</small>
                    </div>
                    """

                acciones_items = "".join([f"<li>{esc(a)}</li>" for a in eje.get('acciones_sugeridas', [])])
                acciones_html = (
                    f"<p><b>Bloqueos Sugeridos:</b></p><ul style=\"font-size:13px; padding-left:20px;\">{acciones_items}</ul>"
                    if acciones_items else "<p><small>Sin bloqueos sugeridos para esta taxonomía.</small></p>"
                )

                st.markdown(f"""
                <div class="agent-card">
                    <div class="agent-header">
                        <div class="agent-name">🛡️ 3. Agente Ejecutor (HU-2.3.x)</div>
                        <span class="{badge_class}">ARIC: {marcacion}</span>
                    </div>
                    <div class="io-label">📥 Input</div>
                    <div class="io-box">
                        Clasificación Final (Analista): <b>{esc(ana.get('clasificacion_final'))}</b> | Confirmado: {ana.get('confirmado')}<br/>
                        Nivel de Incertidumbre: {ana.get('nivel_incertidumbre')}
                    </div>
                    <div class="io-label">📤 Output — Marcación Final</div>
                    <div class="io-box output">
                        <p><b>Acción Operativa:</b> {esc(eje.get('accion_operativa'))}</p>
                        {acciones_html}
                        <p><small><b>Observación ARIC:</b> <code>{esc(eje.get('observacion_aric'))}</code></small></p>
                        <p><small><b>ID Trazabilidad:</b> <code>{esc(eje.get('trazabilidad_id'))}</code></small></p>
                        {vb_html}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with col_a2:
                # 2. ANALISTA
                esc_badge = '<span class="badge-risk">ESCALAR A HUMANO</span>' if ana.get('requiere_escalamiento') else '<span class="badge-norisk">DECISIÓN AUTÓNOMA</span>'

                marcacion_ana = ana.get('marcacion_aric', 'N/A')
                marcacion_badge_class = ("badge-risk" if marcacion_ana == "RISK"
                                          else "badge-norisk" if marcacion_ana == "NO_RISK"
                                          else "badge-suspected")

                evidencias_items = "".join([f"<li>{esc(ev)}</li>" for ev in ana.get('evidencia', [])])

                st.markdown(f"""
                <div class="agent-card">
                    <div class="agent-header">
                        <div class="agent-name">🔍 2. Agente Analista (HU-2.2.x)</div>
                        {esc_badge}
                    </div>
                    <div class="io-label">📥 Input</div>
                    <div class="io-box">
                        Triage Inicial (Clasificador): <b>{esc(clas.get('marcacion_aric'))}</b><br/>
                        Perfil Histórico (Perfilador): <i>"{esc(perf.get('perfil_historico'))}"</i>
                    </div>
                    <div class="io-label">📤 Output — Tipología Ratificada / Rectificada</div>
                    <div class="io-box output">
                        <p><b>Marcación de Riesgo (target):</b> <span class="{marcacion_badge_class}">{marcacion_ana}</span>
                           <small>(derivada determinísticamente, no vía LLM)</small></p>
                        <p><b>Clasificación Final:</b> <code style="color:#00E5FF;">{esc(ana.get('clasificacion_final'))}</code> (Confirmado: {ana.get('confirmado')})</p>
                        <p><b>Modus Operandi:</b> {esc(ana.get('modus_operandi'))}</p>
                        <p><b>Hipótesis Refutadora (Abogado del Diablo):</b><br/><i>"{esc(ana.get('hipotesis_refutadora'))}"</i></p>
                        <p><b>Puntos de Evidencia:</b></p>
                        <ul style="font-size:13px; padding-left:20px;">
                            {evidencias_items}
                        </ul>
                        <p><small><b>Nivel de Incertidumbre:</b> {ana.get('nivel_incertidumbre')}</small></p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # 4. DOCUMENTADOR
                var_badge = '<span class="badge-risk">NUEVA VARIANTE DETECTADA</span>' if doc.get('es_nueva_variante') else '<span class="badge-norisk">VARIANTE ESTÁNDAR</span>'

                st.markdown(f"""
                <div class="agent-card">
                    <div class="agent-header">
                        <div class="agent-name">📝 4. Agente Documentador (HU-2.4.x)</div>
                        {var_badge}
                    </div>
                    <div class="io-label">📥 Input</div>
                    <div class="io-box">
                        Clasificador: <b>{esc(clas.get('marcacion_aric'))}</b> → Analista: <b>{esc(ana.get('clasificacion_final'))}</b> → Ejecutor: <b>{esc(eje.get('marcacion_aric'))}</b><br/>
                        Trazabilidad: <code>{esc(eje.get('trazabilidad_id'))}</code>
                    </div>
                    <div class="io-label">📤 Output</div>
                    <div class="io-box output">
                        <p><b>Resumen Ejecutivo de Cierre:</b><br/>{esc(doc.get('resumen_ejecutivo'))}</p>
                        <p><small><b>Notificar Analista Senior:</b> {doc.get('notificar_senior')}</small></p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                with st.expander("📄 Ver reporte de cierre completo (Markdown)"):
                    st.markdown(doc.get('reporte_cierre_markdown', '_Sin reporte generado._'))

            # --- RENDIMIENTO DE SLAs ---
            perf_sec = res_body.get("performance_seconds", {})
            st.markdown("#### ⏱️ Desglose de SLA y Tiempos de Respuesta")
            m0, m1, m2, m3, m4, m5 = st.columns(6)
            m0.metric("Perfilador", f"{perf_sec.get('perfilador', 0)}s", "LangChain")
            m1.metric("Clasificador", f"{perf_sec.get('clasificador', 0)}s", "SLA <= 5s")
            m2.metric("Analista", f"{perf_sec.get('analista', 0)}s", "SLA <= 10s")
            m3.metric("Ejecutor", f"{perf_sec.get('ejecutor', 0)}s", "SLA <= 5s")
            m4.metric("Documentador", f"{perf_sec.get('documentador', 0)}s", "Batch")
            m5.metric("TOTAL PIPELINE", f"{perf_sec.get('total', 0)}s", "SLA <= 300s")

        else:
            st.error(f"Error en ejecución: {response['body']}")

# ------------------------------------------------------------------------------
# TAB 2: CONSOLA DEL ANALISTA HUMANO (HITL)
# ------------------------------------------------------------------------------
with tab2:
    st.subheader("🚨 Consola de Atención para Analistas del Centro de Fraude (Human-in-the-Loop)")
    st.info("Esta consola presenta los casos con **Alta Incertidumbre** escalados automáticamente por ARIA para toma de decisión asistida.")
    st.warning("🧪 **DATO DE MAQUETA (MOCK):** el caso mostrado abajo es fijo, no proviene del pipeline real ni del Tab 1. Sirve solo para ilustrar el diseño de la consola HITL.")

    col_h1, col_h2 = st.columns([2, 1])
    
    with col_h1:
        st.markdown("""
        <div class="agent-card">
            <div class="agent-header">
                <div class="agent-name">CASO #8614703 — Cliente: Héctor Murcia (CC 1.000.001.066)</div>
                <span class="badge-suspected">ESTADO: PENDIENTE ACCIÓN MANUAL</span>
            </div>
            <p><b>Detalle Operativo:</b> Transferencia por <b>$3,000,000 COP</b> vía canal Glomo (<code>SMGG20210247 - postIdentityDocumentTransfers</code>).</p>
            <hr style="border-color:rgba(255,255,255,0.1);"/>
            <h5>🔍 Razonamiento Pre-armado por los Agentes ARIA:</h5>
            <ul style="font-size:14px;">
                <li><b>Agente Clasificador:</b> Clasificó inicialmente como <code>[NF___FALSO_POSITIVO]</code> por ausencia de virus de control remoto (RAT/Bot = 0).</li>
                <li><b>Agente Analista (Conflicto de Señales):</b> Refutó al Clasificador debido a que el <b>Biocatch Score es 930</b> (Anomalía Biométrica Severa) y el <b>Featurespace Score es 84465</b> en un servicio atípico de transferencia por documento de identidad.</li>
                <li><b>Agente Ejecutor:</b> Marcó <code>RISK_SUSPECTED</code> y activó llamada de confirmación por VoiceBot.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
    with col_h2:
        st.markdown("#### ⚡ Acciones Recomendadas")
        st.button("🛑 CONFIRMAR BLOQUEO PRECAUTORIO (RISK)", type="primary", use_container_width=True)
        st.button("✅ LIBERAR Y DESCHARTAR (NO_RISK)", use_container_width=True)
        st.button("📞 RE-MARCAR LLAMADA VOICEBOT INDRA", use_container_width=True)
        
        st.markdown("---")
        st.markdown("##### 📊 Scores de Riesgo Convergentes")
        st.progress(0.93, text="Biocatch Score: 930 / 1000 (Riesgo Crítico)")
        st.progress(0.84, text="Featurespace Model: 84465 / 100000 (Riesgo Alto)")

# ------------------------------------------------------------------------------
# TAB 3: DASHBOARD DE MÉTRICAS & SLAS
# ------------------------------------------------------------------------------
with tab3:
    st.subheader("📊 Dashboard de Control y Gobernanza de Fraude ARIA")

    _eval_path = os.path.join(_ROOT_DIR, "output", "eval_results.json")
    if not os.path.exists(_eval_path):
        st.warning(
            "No se encontró `output/eval_results.json`. Genera resultados reales corriendo:\n\n"
            "```bash\npython scripts/eval_no_gt.py\n```"
        )
    else:
        with open(_eval_path, "r", encoding="utf-8") as f:
            eval_data = json.load(f)

        summary = eval_data.get("summary", {})
        metrics_gt = eval_data.get("metrics_con_gt", {})

        st.caption(
            f"📅 Generado: {esc(eval_data.get('generated_at', 'N/A'))} · "
            f"Alcance: {esc(eval_data.get('scope', 'N/A'))} · "
            f"Fuente: `output/eval_results.json` (generado por `scripts/eval_no_gt.py`)"
        )

        _escalamiento = summary.get("tasa_escalamiento", 0)
        _sla_pct = summary.get("sla_cumplido_pct", 0)
        _fallback_pct = summary.get("tasa_fallback", 0)

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            kpi_tile("Casos Evaluados", str(summary.get("total_casos", "N/A")), "#E2E8F0")
        with k2:
            kpi_tile("Tasa de Escalamiento a Humano", f"{_escalamiento * 100:.0f}%", "#8FA6BF")
        with k3:
            kpi_tile("SLA Cumplido", f"{_sla_pct * 100:.0f}%", kpi_color(_sla_pct, good=0.9, warn=0.6))
        with k4:
            kpi_tile("Tasa de Fallback (errores)", f"{_fallback_pct * 100:.0f}%", kpi_color(_fallback_pct, good=0.05, warn=0.2, invert=True))

        st.markdown("---")

        if metrics_gt:
            st.markdown("##### 🎯 Evaluación contra Ground Truth (Recall, F1-Score, Matriz de Confusión)")
            n_total = metrics_gt.get("n_total_casos", "N/A")
            n_gt = metrics_gt.get("n_casos_con_gt_confiable", "N/A")
            st.info(
                f"⚠️ Muestra pequeña: **n={n_gt} de {n_total}** casos con Ground Truth confiable "
                f"(`marcacion_final` real de la hoja 'Muestra', excluyendo cierres automáticos no evaluados). "
                f"Estos números son **ilustrativos**, no una línea base estadísticamente significativa."
            )

            def _render_metrics_block(block: dict):
                if not block:
                    st.info("Sin datos para este bloque.")
                    return
                labels = block.get("labels", [])
                macro = block.get("macro_avg", {})
                acc = block.get("accuracy", 0)
                n_clases = len(labels) or 1

                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    kpi_tile("Accuracy", f"{acc * 100:.1f}%", kpi_color(acc, good=0.6, warn=1 / n_clases),
                              sub=f"referencia: {100/n_clases:.0f}% = azar")
                with c2:
                    kpi_tile("F1-Score (macro)", f"{macro.get('f1', 0):.3f}", kpi_color(macro.get('f1', 0), good=0.6, warn=0.3))
                with c3:
                    kpi_tile("Recall (macro)", f"{macro.get('recall', 0):.3f}", kpi_color(macro.get('recall', 0), good=0.6, warn=0.3))
                with c4:
                    kpi_tile("Precision (macro)", f"{macro.get('precision', 0):.3f}", kpi_color(macro.get('precision', 0), good=0.6, warn=0.3))

                per_class = block.get("per_class", [])
                if per_class:
                    st.markdown("**Métricas por clase**")
                    st.dataframe(pd.DataFrame(per_class), use_container_width=True, hide_index=True)

                cm = block.get("confusion_matrix", [])
                if cm and labels:
                    st.markdown("**Matriz de Confusión** (filas = real, columnas = predicho)")
                    st.caption("🟩 verde = acierto en la diagonal · 🟥 rojo = error, más oscuro cuanto más casos")
                    st.dataframe(style_confusion_matrix(cm, labels), use_container_width=True)

            eval_tab_a, eval_tab_c = st.tabs([
                "🔍 Agente Analista (decisión final ratificada)",
                "⏱️ Agente Clasificador (triage inicial)",
            ])
            with eval_tab_a:
                _render_metrics_block(metrics_gt.get("analista_vs_gt", {}))
            with eval_tab_c:
                _render_metrics_block(metrics_gt.get("clasificador_vs_gt", {}))
        else:
            st.info("El archivo de resultados no incluye `metrics_con_gt` (evaluación contra Ground Truth).")

        st.markdown("---")

        col_g1, col_g2 = st.columns(2)

        with col_g1:
            st.markdown(f"##### 📌 Distribución Real de Incertidumbre (n={summary.get('total_casos', '?')})")
            dist_incert = summary.get("distribucion_incertidumbre", {})
            if dist_incert:
                st.bar_chart(dist_incert)
            else:
                st.info("Sin datos.")

        with col_g2:
            st.markdown(f"##### 🏷️ Taxonomías Reales Asignadas por el Analista (n={summary.get('total_casos', '?')})")
            dist_clas = summary.get("distribucion_clasificacion_final", {})
            if dist_clas:
                st.bar_chart(dist_clas)
            else:
                st.info("Sin datos.")

# ------------------------------------------------------------------------------
# TAB 4: PILOTO BLIND TEST SOBRE LAS 200 MUESTRAS BALANCEADAS
# ------------------------------------------------------------------------------
with tab4:
    st.subheader("🧪 Piloto Blind Test — Pipeline completo vs. dataset balanceado de 200 casos")
    st.caption(
        "Corre `scripts/run_pilot_alerts_por_gt.py`: invoca el pipeline completo (5 agentes) "
        "contra una muestra estratificada por GT (RISK/NO_RISK/RISK_SUSPECTED) de "
        "`Muestra_200_ARIA_alerts_por_gt.json`, con el GT retirado del payload antes de invocar "
        "(blind test real, igual que en el Tab 1)."
    )

    _pilots_dir = os.path.join(_ROOT_DIR, "output", "pilots")
    _registry_path = os.path.join(_pilots_dir, "registry.jsonl")
    _experimentos = []
    if os.path.exists(_registry_path):
        _ultimo_evento_por_run = {}
        with open(_registry_path, "r", encoding="utf-8") as f:
            for _linea in f:
                _linea = _linea.strip()
                if not _linea:
                    continue
                _ev = json.loads(_linea)
                _ultimo_evento_por_run[_ev["run_id"]] = _ev  # el ultimo evento de cada run_id gana
        _experimentos = sorted(_ultimo_evento_por_run.values(), key=lambda e: e.get("timestamp", ""), reverse=True)

    _pilot_path = os.path.join(_ROOT_DIR, "output", "pilot_alerts_por_gt_results.json")
    if _experimentos:
        _estado_badge = {"iniciado": "🟡", "reanudado": "🟡", "completado": "🟢", "interrumpido": "🔴"}

        def _fmt_experimento(run_id):
            e = next(x for x in _experimentos if x["run_id"] == run_id)
            badge = _estado_badge.get(e.get("evento"), "⚪")
            n = e.get("casos_procesados", e.get("total", "?"))
            total_e = e.get("total_casos", e.get("total", "?"))
            return f"{badge} {run_id} — {e.get('evento')} ({n}/{total_e} casos, {e.get('workers', '?')} workers)"

        run_id_sel = st.selectbox(
            "Experimento (de output/pilots/registry.jsonl):",
            [e["run_id"] for e in _experimentos],
            format_func=_fmt_experimento,
        )
        _run_summary_path = os.path.join(_pilots_dir, run_id_sel, "summary.json")
        if os.path.exists(_run_summary_path):
            _pilot_path = _run_summary_path

    if not os.path.exists(_pilot_path):
        st.warning(
            "No se encontró ningún resultado de piloto todavía. Genera resultados corriendo:\n\n"
            "```bash\npython scripts/run_pilot_alerts_por_gt.py --total 100 --workers 3\n```"
        )
    else:
        with open(_pilot_path, "r", encoding="utf-8") as f:
            pilot_data = json.load(f)

        casos = pilot_data.get("casos", [])
        evaluados_casos = [c for c in casos if "coincide" in c]

        _estado_txt = {"en_progreso": "🟡 en progreso", "completado": "🟢 completado", "interrumpido": "🔴 interrumpido"}.get(
            pilot_data.get("estado"), ""
        )
        st.caption(
            f"📅 Generado: {esc(pilot_data.get('generated_at', 'N/A'))} · {_estado_txt} · "
            f"{esc(pilot_data.get('casos_procesados', len(casos)))}/{esc(pilot_data.get('total_casos', '?'))} casos procesados · "
            f"Fuente: `{os.path.relpath(_pilot_path, _ROOT_DIR)}`"
        )
        if pilot_data.get("estado") == "en_progreso":
            st.info("⏳ Este experimento sigue corriendo — estos números son parciales y se van a actualizar solos si volvés a esta pestaña más tarde.")

        acc = pilot_data.get("accuracy")
        tiempo_max = pilot_data.get("tiempo_maximo_seg", 0)
        sla_objetivo = 300

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            kpi_tile("Casos evaluados", f"{pilot_data.get('evaluados', 0)}/{pilot_data.get('total_casos', 0)}", "#E2E8F0")
        with k2:
            kpi_tile("Accuracy vs GT", f"{acc:.0%}" if acc is not None else "N/A",
                      kpi_color(acc, good=0.6, warn=0.35), sub="referencia: 33% = azar con 3 clases")
        with k3:
            kpi_tile("Tiempo promedio/caso", f"{pilot_data.get('tiempo_promedio_seg', 0):.1f}s", "#E2E8F0")
        with k4:
            kpi_tile("Tiempo máximo", f"{tiempo_max:.1f}s",
                      kpi_color(tiempo_max, good=sla_objetivo, warn=sla_objetivo * 2, invert=True),
                      sub=f"SLA objetivo: {sla_objetivo}s")

        st.markdown("")
        fallback_agente = pilot_data.get("fallback_por_agente", {})
        if fallback_agente:
            st.warning("⚠️ Fallbacks detectados por agente: " + ", ".join(f"{k}={v}" for k, v in fallback_agente.items()))
        else:
            st.success("✅ Sin fallbacks — todos los agentes respondieron con salida estructurada válida en cada caso.")

        st.markdown("---")

        labels = ["RISK", "NO_RISK", "RISK_SUSPECTED"]
        st.markdown("##### Matriz de Confusión (real GT → predicho por Ejecutor)")
        st.caption("🟩 verde = acierto en la diagonal · 🟥 rojo = error, más oscuro cuanto más casos")
        if evaluados_casos:
            # Recalculada desde `casos` en vez de leer el bloque "confusion_matrix" del JSON:
            # corridas hechas con una versión anterior del script no lo incluyen todavía.
            matriz = {real: {pred: 0 for pred in labels} for real in labels}
            for c in evaluados_casos:
                real = c.get("gt_esperado")
                pred = c.get("marcacion_predicha")
                if real in matriz and pred in matriz[real]:
                    matriz[real][pred] += 1
            cm = [[matriz[real][pred] for pred in labels] for real in labels]
            st.dataframe(style_confusion_matrix(cm, labels), use_container_width=True)

            st.markdown("")
            st.caption("Recall por clase — de los casos que REALMENTE son de esta clase, cuántos acertó el pipeline")
            rc1, rc2, rc3 = st.columns(3)
            for col, real in zip((rc1, rc2, rc3), labels):
                total_real = sum(matriz[real].values())
                aciertos_real = matriz[real][real]
                recall = aciertos_real / total_real if total_real else None
                with col:
                    kpi_tile(
                        f"Recall {real}",
                        f"{recall:.0%}" if recall is not None else "N/A",
                        kpi_color(recall, good=0.5, warn=0.3) if recall is not None else "#6E85A3",
                        sub=f"{aciertos_real}/{total_real} casos" if total_real else "sin casos",
                    )

            st.markdown("---")
            st.markdown("##### Accuracy por agente")
            st.caption(
                "Clasificador, Analista y Ejecutor deciden RISK / NO_RISK / RISK_SUSPECTED cada uno por su cuenta: "
                "el Clasificador vía LLM directo en su triage rápido, el Analista de forma determinística a partir "
                "de la taxonomía FCP que asigna (`agents/_marcacion.py`), y el Ejecutor vía su propio LLM — esa "
                "última es la marcación oficial que se reporta y se compara contra el ground truth."
            )
            _agentes_metricas = [
                ("Clasificador", "marcacion_predicha_clasificador", "coincide_clasificador"),
                ("Analista", "marcacion_predicha_analista", "coincide_analista"),
                ("Ejecutor (oficial)", "marcacion_predicha", "coincide"),
            ]
            _tiene_desglose = any(c.get("coincide_clasificador") is not None for c in evaluados_casos)
            if _tiene_desglose:
                cols_ag = st.columns(3)
                for col, (nombre, campo_pred, campo_coincide) in zip(cols_ag, _agentes_metricas):
                    aciertos_ag = sum(1 for c in evaluados_casos if c.get(campo_coincide))
                    acc_ag = aciertos_ag / len(evaluados_casos) if evaluados_casos else None
                    with col:
                        kpi_tile(
                            f"Accuracy {nombre}",
                            f"{acc_ag:.0%}" if acc_ag is not None else "N/A",
                            kpi_color(acc_ag, good=0.6, warn=0.35) if acc_ag is not None else "#6E85A3",
                            sub=f"{aciertos_ag}/{len(evaluados_casos)} casos",
                        )
            else:
                st.info("Esta corrida no tiene desglose de accuracy por agente (generada con una versión anterior del script).")
        else:
            st.info("Sin casos evaluados todavía.")

        st.markdown("---")

        st.markdown("##### Consumo de tokens por agente")
        tokens_por_agente = pilot_data.get("tokens_por_agente")
        if not tokens_por_agente:
            # Compatibilidad con corridas hechas antes de capturar tokens.
            agentes_orden = ["perfilamiento", "clasificador", "analista", "ejecutor", "documentador"]
            tokens_por_agente = {a: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llamadas": 0} for a in agentes_orden}
            for c in casos:
                for a, t in c.get("tokens_por_agente", {}).items():
                    for k in ("input_tokens", "output_tokens", "total_tokens", "llamadas"):
                        tokens_por_agente[a][k] += t.get(k, 0)

        tokens_totales = pilot_data.get("tokens_totales") or sum(t["total_tokens"] for t in tokens_por_agente.values())
        if tokens_totales:
            tt1, tt2 = st.columns([1, 3])
            with tt1:
                kpi_tile("Tokens totales del batch", f"{tokens_totales:,}", "#00E5FF",
                          sub=f"{tokens_totales / max(pilot_data.get('evaluados', 1), 1):,.0f} tokens/caso promedio")
            with tt2:
                df_tokens = pd.DataFrame([
                    {"Agente": a.capitalize(), "Input": t["input_tokens"], "Output": t["output_tokens"], "Total": t["total_tokens"]}
                    for a, t in tokens_por_agente.items()
                ]).set_index("Agente")
                st.bar_chart(df_tokens[["Input", "Output"]])
            st.dataframe(
                pd.DataFrame([
                    {"Agente": a.capitalize(), "Input tokens": t["input_tokens"], "Output tokens": t["output_tokens"],
                     "Total": t["total_tokens"], "Llamadas": t["llamadas"]}
                    for a, t in tokens_por_agente.items()
                ]),
                use_container_width=True, hide_index=True,
            )

            # costo_por_agente_usd ya viene calculado en corridas nuevas (ver
            # scripts/run_pilot_alerts_por_gt.py); para corridas viejas se recalcula
            # aquí mismo a partir de los tokens agregados con la tarifa vigente en
            # pricing.yaml -- por eso puede no coincidir centavo a centavo con lo que
            # costó realmente esa corrida si la tarifa cambió desde entonces.
            model_id = pilot_data.get("model_id")
            costo_por_agente = pilot_data.get("costo_por_agente_usd") or calcular_costos_por_agente(tokens_por_agente, model_id)
            costo_total_usd = pilot_data.get("costo_total_usd")
            if costo_total_usd is None:
                costo_total_usd = sum(costo_por_agente.values())

            st.markdown("##### Costo estimado (USD)")
            ct1, ct2 = st.columns([1, 3])
            with ct1:
                kpi_tile("Costo total del batch", f"${costo_total_usd:,.4f}", "#00E676",
                          sub=f"${costo_total_usd / max(pilot_data.get('evaluados', 1), 1):,.5f}/caso promedio"
                              + (f" · {model_id}" if model_id else ""))
            with ct2:
                df_costo = pd.DataFrame([
                    {"Agente": a.capitalize(), "Costo USD": costo_por_agente.get(a, 0.0)}
                    for a in tokens_por_agente
                ]).set_index("Agente")
                st.bar_chart(df_costo)
        else:
            st.info("Esta corrida no tiene datos de consumo de tokens (generada con una versión anterior del script).")

        st.markdown("---")
        st.markdown("##### Detalle por caso")
        for c in casos:
            if "coincide" in c:
                badge = "✅" if c["coincide"] else "❌"
                titulo = f"{badge} Customer {c.get('customerid')} — GT: {c.get('gt_esperado')} | Predicho: {c.get('marcacion_predicha')}"
            else:
                badge = "⚠️"
                titulo = f"{badge} Customer {c.get('customerid', 'N/A')} — Error en ejecución"
            with st.expander(titulo):
                if "coincide" in c:
                    st.markdown(f"**Clasificación final (Analista):** `{esc(c.get('clasificacion_final'))}`")
                    st.markdown(f"**Nivel de incertidumbre:** {esc(c.get('nivel_incertidumbre'))} · "
                                f"**Escalamiento:** {c.get('requiere_escalamiento')}")
                    st.markdown(f"**Tiempo total:** {c.get('tiempo_seg')}s")
                    perf = c.get("performance_seconds", {})
                    if perf:
                        st.json(perf)
                else:
                    st.error(c.get("error", "Sin detalle de error."))

st.markdown("---")
st.markdown("<center><small>BBVA Colombia — Sistema Multiagente ARIA v1.0 | Powered by Amazon Bedrock & Claude Sonnet 4.6</small></center>", unsafe_allow_html=True)
