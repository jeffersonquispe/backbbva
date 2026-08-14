"""
Agente Analista ARIA (HU-2.2.1, HU-2.2.2, HU-2.2.3, HU-2.2.4).
Realiza la verificación adversarial frente a la decisión del Clasificador para reducir falsos positivos/negativos.
"""

import os
from typing import Optional, List, Literal

from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AlertInput, ClasificadorOutput, AnalistaOutput, PerfilamientoOutput
from agents._taxonomia import TAXONOMIAS_PERMITIDAS, _TaxonomiaFCP
from agents._resilience import invoke_with_retry, log_fallback, TokenUsageCallback
from agents._risk_scales import format_biocatch, format_model_score
from agents._marcacion import derivar_marcacion_aric as _derivar_marcacion_aric
from agents._modus_operandi import catalogo_como_texto, modus_operandi_por_taxonomia


class _AnalistaLLMSchema(BaseModel):
    """Esquema de salida estructurada exigido al LLM vía LangChain.

    'clasificacion_final' usa el mismo Literal cerrado que el Clasificador
    (_TaxonomiaFCP): antes, como texto libre, el Analista inventaba categorías
    fuera del set FCP el 80% de las veces (ver docs/HU-Perfilamiento.md). Forzar
    el tipo aquí hace que una respuesta inválida falle la validación de Pydantic
    -- y por lo tanto caiga al fallback de forma visible -- en vez de aceptarse
    en silencio como antes.
    """

    confirmado: bool = Field(description="True si el Analista confirma el triage de riesgo inicial del Clasificador.")
    clasificacion_final: _TaxonomiaFCP = Field(
        description="Taxonomía FCP confirmada o rectificada. Debes elegir EXACTAMENTE uno de los valores permitidos, incluso si rectificas la clasificación inicial."
    )
    hipotesis_refutadora: str = Field(description="Máximo 1-2 oraciones breves (máx. 25 palabras).")
    evidencia: List[str] = Field(description="Máximo 2-3 puntos breves y directos (máx. 15 palabras por punto).")
    nivel_incertidumbre: Literal["BAJO", "MEDIO", "ALTO"] = Field(description="Nivel de incertidumbre tras el análisis adversarial.")
    requiere_escalamiento: bool = Field(description="True si el nivel de incertidumbre es ALTO.")
    razon_escalamiento: Optional[str] = Field(default=None, description="1 oración corta si requiere escalamiento, o None.")


class AnalistaAgent:
    """Agente Analista para verificación adversarial y reducción de incertidumbre."""

    # Mismo problema y mismo fix que en PerfiladorAgent.MAX_HISTORIAL_TXS_EN_PROMPT:
    # dumpear el historial completo sin recortar infla el prompt (clientes con
    # cientos de transacciones) y ya se vio en métricas reales que el Analista
    # concentra la mayor parte del consumo de tokens del pipeline por esto.
    MAX_HISTORIAL_TXS_EN_PROMPT = 30

    _CATALOGO_FCP = catalogo_como_texto()

    SYSTEM_PROMPT = f"""Eres el Agente Analista del sistema ARIA para BBVA.
Tu rol es actuar de forma ADVERSARIAL frente al triage de riesgo tomado por el Agente
Clasificador (RISK / NO_RISK / RISK_SUSPECTED). NO lo confirmes pasivamente. Debes
cuestionarlo generando hipótesis contradictorias. Además, sos vos quien asigna la
taxonomía FCP definitiva del caso -- el Clasificador ya no la propone, solo te pasa
un triage de riesgo rápido para que lo verifiques.

CATÁLOGO DE MODUS OPERANDI / TAXONOMÍAS FCP (señales típicas de cada MO para
ubicar el caso al asignar 'clasificacion_final'):
{_CATALOGO_FCP}

REGLAS DE CONCISIÓN Y ANÁLISIS ADVERSARIAL:
1. 'hipotesis_refutadora': Sé ULTRA CONCISO. Máximo 1 o 2 oraciones breves (máximo 25 palabras).
2. 'evidencia': Máximo 2 a 3 puntos breves y directos (máximo 15 palabras por punto).
3. 'razon_escalamiento': 1 oración corta y directa si requiere escalamiento, o None.
4. Analiza scores (Biocatch, Featurespace), biometría (RAT, Emulator, Bot), techos de monto y marcas temporales.
5. Determina incertidumbre (BAJO, MEDIO, ALTO). Si es ALTO, fija 'requiere_escalamiento': true.
6. 'clasificacion_final' DEBE ser exactamente uno de los valores del conjunto cerrado FCP
   -- sos el primer y único agente que la asigna, el Clasificador no propone ninguna:
   {TAXONOMIAS_PERMITIDAS}
7. Los scores de Biocatch/Featurespace solo detectan fraude TÉCNICO (RAT, malware,
   desviación de hábito) — el fraude por ingeniería social o robo físico (vishing,
   estafa, celular robado) no deja huella ahí porque el titular real opera la sesión.
   No bajes la incertidumbre solo porque el score es bajo: mirá si el perfilamiento
   describe contraparte nueva, vaciamiento progresivo tras un desembolso grande, o
   quiebre abrupto de hábito — esas señales narrativas justifican incertidumbre BAJA
   (o sea, confirmar fraude) por sí solas, con o sin score alto.
8. Al revés, un score alto SIN ninguna señal narrativa de fraude suele ser una alerta
   que se abrió y no se confirmó — no subas la incertidumbre solo por el número; mirá
   si hay evidencia real de vaciamiento/contraparte nueva antes de escalar.
9. Si se entrega 'Razón de Marcación' (nota histórica de otro sistema/analista),
   trátala como un dato más a contrastar adversarialmente, no como veredicto: no
   estás obligado a que 'clasificacion_final' coincida con ella.
"""

    def __init__(
        self,
        llm: Optional[ChatBedrock] = None,
        model_id: Optional[str] = None,
        region_name: Optional[str] = None,
    ):
        self.llm = llm or ChatBedrock(
            model_id=model_id or os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
            region_name=region_name or os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            model_kwargs={"temperature": 0.1, "max_tokens": 2500},
        )
        self._structured_llm = self.llm.with_structured_output(_AnalistaLLMSchema)

    def process(
        self,
        alert: AlertInput,
        clasificacion_inicial: ClasificadorOutput,
        perfilamiento: Optional[PerfilamientoOutput] = None,
    ) -> AnalistaOutput:
        """Somete la clasificación del Clasificador a revisión adversarial.

        Si se provee `perfilamiento` (HU-2.0.x), su texto consolidado se agrega
        como contexto semántico adicional al cuestionamiento crítico (HU-2.2.5).
        """
        recent_txs = alert.get_recent_transactions()
        historial_para_prompt = recent_txs[: self.MAX_HISTORIAL_TXS_EN_PROMPT]
        historial_truncado_nota = (
            f" (mostrando las {self.MAX_HISTORIAL_TXS_EN_PROMPT} más recientes de {len(recent_txs)} totales)"
            if len(recent_txs) > self.MAX_HISTORIAL_TXS_EN_PROMPT
            else ""
        )

        perfilamiento_bloque = (
            f"""
CONTEXTO SEMÁNTICO GENERADO POR EL AGENTE DE PERFILAMIENTO:
{perfilamiento.texto_consolidado}
"""
            if perfilamiento is not None
            else ""
        )
        razon_marcacion_bloque = (
            f"- Razón de Marcación (contexto adicional, no vinculante — ver regla 9): {alert.razon_marcacion}\n"
            if alert.razon_marcacion
            else ""
        )

        human_prompt = f"""
ANÁLISIS ADVERSARIAL DE ALERTA:
- Customer ID: {alert.customerid}
- Triage Inicial del Clasificador (marcación de riesgo, no taxonomía): {clasificacion_inicial.marcacion_aric}
- Justificación del Clasificador: {clasificacion_inicial.cot_justificacion}
- Regla Cold Start Aplicada: {clasificacion_inicial.regla_cold_start_aplicada}
{razon_marcacion_bloque}{perfilamiento_bloque}
DATOS DE EVIDENCIA TRANSACCIONAL:
- Evento / Canal / Servicio: {alert.eventtype} | {alert.channel} | {alert.integrationpoint}
- Monto Alerta: ${alert.amount_value:,.2f} COP
- Biocatch Score: {format_biocatch(alert.biocatch_score)} | Featurespace Model Score: {format_model_score(alert.Model_score)}
- Banderas Técnicas Biocatch: RAT={alert.biocatch_isRat}, MobileRAT={alert.biocatch_isMobileRat}, Emulator={alert.biocatch_isEmulator}, Bot={alert.biocatch_isBot}
- Techos Históricos de Monto: PSE=${alert.MontoMasAltoPSE:,.2f}, BreB=${alert.MontoMasAltoBreB:,.2f}, Glomo=${alert.MontoMasAltoGlomo:,.2f}, Net=${alert.MontoMasAltoNet:,.2f}
- Historial Reciente{historial_truncado_nota}: {historial_para_prompt}

Cuestiona activamente el triage inicial ('{clasificacion_inicial.marcacion_aric}') del Clasificador y asigná la taxonomía FCP definitiva del caso. Considera tanto el contexto semántico del perfilamiento (si está presente) como los datos crudos de evidencia. Busca contradicciones y concluye si se confirma o rectifica el triage.
"""

        token_cb = TokenUsageCallback()
        try:
            result: _AnalistaLLMSchema = invoke_with_retry(
                self._structured_llm,
                [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=human_prompt),
                ],
                agent_name="Analista",
                token_callback=token_cb,
            )

            marcacion_aric = _derivar_marcacion_aric(
                result.clasificacion_final, result.nivel_incertidumbre, result.requiere_escalamiento
            )

            return AnalistaOutput(
                confirmado=result.confirmado,
                clasificacion_final=result.clasificacion_final,
                hipotesis_refutadora=result.hipotesis_refutadora,
                evidencia=result.evidencia,
                nivel_incertidumbre=result.nivel_incertidumbre,
                requiere_escalamiento=result.requiere_escalamiento,
                razon_escalamiento=result.razon_escalamiento,
                iteraciones_realizadas=1,
                marcacion_aric=marcacion_aric,
                modus_operandi=modus_operandi_por_taxonomia(result.clasificacion_final),
                metadata={"customerid": alert.customerid, "tokens": token_cb.as_dict()},
            )
        except Exception as e:
            # Fallback seguro segun HU-2.2.4: Escalar si falla el análisis o la
            # validación de schema (incluye 'clasificacion_final' fuera del set cerrado).
            # El Clasificador ya no propone ninguna taxonomía (solo un triage de riesgo),
            # así que no hay nada suyo que reutilizar acá -- se usa un valor neutro de
            # "revisión pendiente"; da igual para el resultado porque requiere_escalamiento
            # ya fuerza revisión humana sin importar la etiqueta.
            log_fallback("Analista", e)
            return AnalistaOutput(
                confirmado=False,
                clasificacion_final="[NF___ANLISIS]",
                hipotesis_refutadora=f"Error técnico durante el análisis adversarial: {str(e)}",
                evidencia=[f"Fallo del servicio Bedrock/validación en Analista: {str(e)}"],
                nivel_incertidumbre="ALTO",
                requiere_escalamiento=True,
                razon_escalamiento=f"Timeout/Error en Agente Analista: {str(e)}",
                iteraciones_realizadas=1,
                marcacion_aric="RISK_SUSPECTED",
                modus_operandi="Sin determinar (fallback técnico -- requiere revisión manual)",
                metadata={"error": str(e), "tokens": token_cb.as_dict()},
            )
