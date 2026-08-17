"""
Agente Ejecutor ARIA (HU-2.3.1, HU-2.3.2, HU-2.3.3).
Toma la decisión operativa final y determina la marcación ARIC y el disparo condicional de VoiceBot.
"""

import os
import uuid
from typing import Optional, Literal

from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AlertInput, AnalistaOutput, EjecutorOutput
from agents._resilience import invoke_with_retry, log_fallback, TokenUsageCallback
from agents._modus_operandi import catalogo_como_texto, acciones_por_taxonomia, formatear_observacion_aric


class _EjecutorLLMSchema(BaseModel):
    """Esquema de salida estructurada exigido al LLM vía LangChain.

    'marcacion_aric' usa un Literal cerrado de 3 valores: si el modelo devuelve
    algo fuera de ese set, la validación de Pydantic falla y el caso cae al
    fallback, en vez de aceptar en silencio una marcación inválida.
    """

    marcacion_aric: Literal["RISK", "NO_RISK", "RISK_SUSPECTED"] = Field(
        description=(
            "RISK: se confirmó fraude o riesgo inminente. NO_RISK: se descartó el "
            "riesgo o es un falso positivo confirmado. RISK_SUSPECTED: incertidumbre "
            "alta, requiere escalamiento a analista humano o callback de VoiceBot."
        )
    )
    disparar_voicebot: bool = Field(
        description="True SOLO si hay sospecha razonable ('risk-suspected') o se requiere validación telefónica inmediata con el cliente."
    )
    motivo_voicebot: Optional[str] = Field(default=None, description="Motivo si se dispara VoiceBot, o None.")
    accion_operativa: str = Field(description="Descripción clara de la acción determinista recomendada.")


class EjecutorAgent:
    """Agente Ejecutor para la decisión operativa final y activación de VoiceBot."""

    _CATALOGO_FCP = catalogo_como_texto()

    SYSTEM_PROMPT = f"""Eres el Agente Ejecutor del sistema ARIA para BBVA.
Tu función es determinar la marcación operativa FINAL hacia ARIC y definir las acciones inmediatas.

CATÁLOGO DE MODUS OPERANDI / TAXONOMÍAS FCP (acciones de contención reales por MO --
usalo como referencia para que 'accion_operativa' describa bloqueos concretos, no
texto genérico):
{_CATALOGO_FCP}

REGLAS DE DECISIÓN OPERATIVA:
1. Marcación ARIC (debe ser estrictamente una de estas 3):
   - RISK: Se confirmó fraude o riesgo inminente de suplantación/malware.
   - NO_RISK: Se descartó el riesgo o es un falso positivo confirmado.
   - RISK_SUSPECTED: Incertidumbre alta, requiere escalamiento a analista humano o callback de VoiceBot.

2. Disparo Condicional de VoiceBot (HU-2.3.2):
   - 'disparar_voicebot': true SOLO si hay sospecha razonable ('risk-suspected') o requerimiento de validación telefónica inmediata con el cliente.
   - NO disparar VoiceBot si el fraude es 100% evidente (congelamiento inmediato) o si es 100% NO_RISK.

3. 'accion_operativa' debe nombrar los bloqueos concretos del catálogo (Baja Softoken,
   Bloqueo Soft/Hard GLOMO/NET, Bloqueo Tarjeta, Bloqueo Cuenta, BAEP Blacklist, etc.)
   correspondientes a la taxonomía FCP del caso, no una descripción genérica.
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
        self._structured_llm = self.llm.with_structured_output(_EjecutorLLMSchema)

    def process(self, alert: AlertInput, analisis: AnalistaOutput) -> EjecutorOutput:
        """Toma la decisión operativa a partir de los hallazgos del Analista."""
        trazabilidad_id = f"aria-trace-{uuid.uuid4().hex[:12]}"

        human_prompt = f"""
DECISIÓN OPERATIVA DE ALERTA:
- Customer ID: {alert.customerid}
- Clasificación Ratificada/Rectificada: {analisis.clasificacion_final}
- Confirmado por Analista: {analisis.confirmado}
- Nivel de Incertidumbre: {analisis.nivel_incertidumbre}
- Requiere Escalamiento Humano: {analisis.requiere_escalamiento}
- Razón de Escalamiento: {analisis.razon_escalamiento}
- Evidencias: {analisis.evidencia}
- Marcación de riesgo ya derivada por el Analista (referencia): {analisis.marcacion_aric}
- Servicio / Canal / Monto: {alert.integrationpoint} | {alert.channel} | ${alert.amount_value:,.2f} COP

Determina la marcación ARIC (RISK, NO_RISK, RISK_SUSPECTED) y si se requiere invocar VoiceBot.
"""

        token_cb = TokenUsageCallback()
        try:
            result: _EjecutorLLMSchema = invoke_with_retry(
                self._structured_llm,
                [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=human_prompt),
                ],
                agent_name="Ejecutor",
                token_callback=token_cb,
            )

            acciones_sugeridas = acciones_por_taxonomia(analisis.clasificacion_final)
            return EjecutorOutput(
                marcacion_aric=result.marcacion_aric,
                disparar_voicebot=result.disparar_voicebot,
                motivo_voicebot=result.motivo_voicebot if result.disparar_voicebot else None,
                accion_operativa=result.accion_operativa,
                trazabilidad_id=trazabilidad_id,
                acciones_sugeridas=acciones_sugeridas,
                observacion_aric=formatear_observacion_aric(
                    analisis.clasificacion_final, alert.channel, habito=None, resumen=result.accion_operativa
                ),
                metadata={"customerid": alert.customerid, "clasificacion_final": analisis.clasificacion_final, "tokens": token_cb.as_dict()},
            )
        except Exception as e:
            # Fallback determinista (incluye validación de schema fallida)
            log_fallback("Ejecutor", e)
            acciones_sugeridas = acciones_por_taxonomia(analisis.clasificacion_final)
            return EjecutorOutput(
                marcacion_aric="RISK_SUSPECTED",
                disparar_voicebot=True,
                motivo_voicebot=f"Fallback automático por error en Ejecutor: {str(e)}",
                accion_operativa="Escalar caso a PostProcess y activar VoiceBot precautorio por fallo en Agente Ejecutor.",
                trazabilidad_id=trazabilidad_id,
                acciones_sugeridas=acciones_sugeridas,
                observacion_aric=formatear_observacion_aric(
                    analisis.clasificacion_final, alert.channel, habito=None,
                    resumen=f"Fallback técnico en Ejecutor: {str(e)}",
                ),
                metadata={"error": str(e), "tokens": token_cb.as_dict()},
            )
