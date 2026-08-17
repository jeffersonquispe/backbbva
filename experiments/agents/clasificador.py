"""
Agente Clasificador ARIA (HU-2.1.1, HU-2.1.2, HU-2.1.3).
Realiza el triage inicial rápido de la alerta transaccional, decidiendo directamente
una marcación de riesgo (RISK / NO_RISK / RISK_SUSPECTED). El catálogo de taxonomías
FCP se usa como conocimiento de referencia para razonar, no como algo que el
Clasificador tenga que reportar -- la taxonomía FCP definitiva la asigna el Analista
(ver agents/analista.py, AnalistaOutput.clasificacion_final).
"""

import os
from typing import Optional, Literal

from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AlertInput, ClasificadorOutput, PerfilamientoOutput
from agents._resilience import invoke_with_retry, log_fallback, TokenUsageCallback
from agents._risk_scales import format_biocatch, format_model_score
from agents._taxonomia import TAXONOMIAS_PERMITIDAS
from agents._modus_operandi import catalogo_como_texto


class _ClasificadorLLMSchema(BaseModel):
    """Esquema de salida estructurada exigido al LLM vía LangChain."""

    marcacion_aric: Literal["RISK", "NO_RISK", "RISK_SUSPECTED"] = Field(
        description=(
            "RISK: evidencia clara de fraude en este triage rápido. NO_RISK: "
            "evidencia clara de operación legítima. RISK_SUSPECTED: evidencia "
            "insuficiente o contradictoria para decidir con confianza en este "
            "primer vistazo -- se manda a verificación adversarial del Analista."
        )
    )
    cot_justificacion: str = Field(
        description=(
            "Resumen ejecutivo del razonamiento, 1-2 oraciones -- qué taxonomía(s) "
            "FCP del catálogo de referencia se ajustan mejor a la evidencia y por qué."
        )
    )
    regla_cold_start_aplicada: bool = Field(
        description="True si se detectó ausencia de historial reciente del usuario y se aplicó la regla Cold Start."
    )


class ClasificadorAgent:
    """Agente Clasificador para triage inicial de alertas en ARIA."""

    # Se mantiene expuesto en la clase por compatibilidad con scripts/eval_no_gt.py
    # y otros consumidores que ya referencian ClasificadorAgent.TAXONOMIAS_PERMITIDAS
    # -- ya no es el set que el Clasificador reporta como salida (ver docstring).
    TAXONOMIAS_PERMITIDAS = TAXONOMIAS_PERMITIDAS

    _CATALOGO_FCP = catalogo_como_texto()

    SYSTEM_PROMPT = f"""Eres el Agente Clasificador del sistema ARIA para BBVA.
Tu objetivo es realizar el triage inicial rápido (máx 5s) de una alerta de posible
fraude y decidir directamente una marcación de riesgo: RISK, NO_RISK o RISK_SUSPECTED.

CATÁLOGO DE MODUS OPERANDI / TAXONOMÍAS FCP (conocimiento de referencia para razonar
-- NO es un campo que tengas que reportar, esa taxonomía definitiva la asigna el
Analista después; las señales típicas de cada MO son las que un analista humano de
fraude ya reconoce de memoria, úsalas para ubicar el caso):
{_CATALOGO_FCP}

REGLAS OBLIGATORIAS:
1. Decide 'marcacion_aric' directamente: RISK si la evidencia se ajusta con claridad
   a alguna categoría FR___ del catálogo; NO_RISK si se ajusta con claridad a alguna
   NF___; RISK_SUSPECTED si la evidencia es insuficiente o contradictoria para
   decidir con confianza en este triage rápido (ver regla 7). No inventes categorías
   fuera del catálogo ni las repitas en tu salida -- son contexto, no el veredicto.

2. Si detectas ausencia de historial del usuario o alta reciente (Regla Cold Start):
   - Evalúa la transacción contra los montos promedio del canal y marca 'regla_cold_start_aplicada': true.

3. Sé conciso en 'cot_justificacion': resumen ejecutivo de 1-2 oraciones.

4. Los scores de Biocatch/Featurespace ARIC (bandas oficiales en "DATOS DE
   RESPALDO") detectan UN tipo de fraude: anomalías técnicas de sesión (RAT,
   malware, emulador, desviación de hábito). NO detectan el otro tipo, igual
   de frecuente en este negocio: ingeniería social o robo físico (vishing,
   estafa telefónica, celular robado ya desbloqueado), donde el titular real
   de la cuenta opera la sesión sin ninguna anomalía técnica que un sensor
   pueda oler. Un score bajo es evidencia de que NO hay fraude técnico — nunca
   evidencia de que no hay fraude. Un score alto SIN ninguna señal narrativa
   de la regla 5 suele ser solo una alerta que se abrió y no debería
   confirmarse (candidato a NO_RISK, tipo [NF___FALSO_POSITIVO]).

5. Señales narrativas de ingeniería social o robo (pesan tanto o más que el
   score cuando el score es bajo): transferencia grande a una contraparte
   nueva o infrecuente; movimiento de fondos poco después de un desembolso
   grande (préstamo, avance, crédito); secuencia de retiros o transferencias
   en ventanas cortas de tiempo ("vaciamiento" progresivo de cuenta); quiebre
   abrupto del patrón habitual sin ninguna causa técnica visible. Si el
   perfilamiento describe dos o más de estas señales, marca RISK aunque los
   scores instrumentales sean bajos.

6. Si se entrega 'Razón de Marcación' (nota histórica de otro sistema/analista),
   úsala solo como contexto adicional para orientar el triage. NO estás
   obligado a que tu marcación coincida con ella ni a reproducirla: sigue
   decidiendo con base en la evidencia de las reglas 1-5.

7. Marca RISK_SUSPECTED cuando: (a) las señales narrativas y los scores
   instrumentales apuntan en direcciones opuestas (ej. score alto sin ninguna
   señal narrativa, o señales narrativas fuertes con score bajo y sin nada más
   que las respalde), o (b) Cold Start sin ninguna señal narrativa ni técnica
   que incline la balanza hacia RISK o NO_RISK. No es el análisis adversarial
   del Analista (eso viene después) -- es reconocer que este triage rápido no
   alcanza para decidir con confianza.
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
            model_kwargs={"temperature": 0.0, "max_tokens": 600},
        )
        self._structured_llm = self.llm.with_structured_output(_ClasificadorLLMSchema)

    def process(
        self,
        alert: AlertInput,
        perfilamiento: Optional[PerfilamientoOutput] = None,
    ) -> ClasificadorOutput:
        """Procesa una alerta y retorna el triage de riesgo estructurado.

        Si se provee `perfilamiento` (HU-2.0.x), la evidencia principal del prompt
        es el texto semántico generado por el Agente de Perfilamiento (HU-2.1.4).
        Si no se provee, conserva el comportamiento anterior basado en campos
        crudos de `AlertInput` (compatibilidad hacia atrás).
        """
        is_cold_start = alert.is_cold_start()
        recent_txs = alert.get_recent_transactions()
        razon_marcacion_bloque = (
            f"- Razón de Marcación (contexto adicional, no vinculante — ver regla 6): {alert.razon_marcacion}\n"
            if alert.razon_marcacion
            else ""
        )

        if perfilamiento is not None:
            human_prompt = f"""
EVALUACIÓN DE ALERTA TRANSACCIONAL ARIA (basada en el perfilamiento semántico):

{perfilamiento.texto_consolidado}

DATOS DE RESPALDO (bandas ya calculadas con los umbrales oficiales de cada proveedor —
solo detectan fraude técnico; una banda BAJA no descarta fraude por ingeniería
social o robo, ver regla 4):
- Score Biocatch: {format_biocatch(alert.biocatch_score)}
- Score Modelo Featurespace ARIC: {format_model_score(alert.Model_score)}
- Regla Cold Start Detectada: {is_cold_start}
{razon_marcacion_bloque}
Decide la marcación de riesgo evaluando primero las señales narrativas del
perfilamiento (contraparte nueva, vaciamiento progresivo, quiebre de hábito —
regla 5). Usa las bandas de score para reforzar sospecha de fraude técnico,
nunca para descartar fraude cuando la narrativa ya muestra señales de riesgo.
"""
        else:
            human_prompt = f"""
EVALUACIÓN DE ALERTA TRANSACCIONAL ARIA:
- Customer ID: {alert.customerid}
- Evento / Canal / Servicio: {alert.eventtype} | {alert.channel} | {alert.integrationpoint}
- Monto Transacción: ${alert.amount_value:,.2f} COP
- Fecha Transacción: {alert.fecha_transaccion}
- Score Biocatch: {format_biocatch(alert.biocatch_score)}
- Score Modelo Featurespace ARIC: {format_model_score(alert.Model_score)}
- Señales Biocatch: MobileRAT={alert.biocatch_isMobileRat}, Emulator={alert.biocatch_isEmulator}, RAT={alert.biocatch_isRat}, Bot={alert.biocatch_isBot}
- Montos Históricos Máximos: PSE=${alert.MontoMasAltoPSE:,.2f}, BreB=${alert.MontoMasAltoBreB:,.2f}, Glomo=${alert.MontoMasAltoGlomo:,.2f}, Net=${alert.MontoMasAltoNet:,.2f}
- Historial Reciente ({len(recent_txs)} txs): {recent_txs[:3]}
- Regla Cold Start Detectada: {is_cold_start}
{razon_marcacion_bloque}
Decide la marcación de riesgo según el catálogo FCP de referencia, evaluando
únicamente los datos primarios de la transacción.
"""

        token_cb = TokenUsageCallback()
        try:
            result: _ClasificadorLLMSchema = invoke_with_retry(
                self._structured_llm,
                [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=human_prompt),
                ],
                agent_name="Clasificador",
                token_callback=token_cb,
            )

            return ClasificadorOutput(
                marcacion_aric=result.marcacion_aric,
                cot_justificacion=result.cot_justificacion,
                regla_cold_start_aplicada=result.regla_cold_start_aplicada,
                metadata={"customerid": alert.customerid, "integrationpoint": alert.integrationpoint, "tokens": token_cb.as_dict()},
            )
        except Exception as e:
            # Fallback seguro segun HU-2.1.2 (incluye validación de schema fallida):
            # un fallo técnico es, por definición, un caso donde el Clasificador no
            # puede sostener ningún triage -- postura conservadora, nunca NO_RISK.
            log_fallback("Clasificador", e)
            return ClasificadorOutput(
                marcacion_aric="RISK_SUSPECTED",
                cot_justificacion=f"Fallback automático por error en generación/validación: {str(e)}",
                regla_cold_start_aplicada=is_cold_start,
                metadata={"error": str(e), "tokens": token_cb.as_dict()},
            )
