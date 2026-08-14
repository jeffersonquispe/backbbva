"""
Agente Documentador ARIA (HU-2.4.1, HU-2.4.2, HU-2.4.3).
Genera la documentación formal de cierre y detecta nuevas variantes de fraude para curación continua.
"""

import os
from typing import Optional

from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AlertInput, ClasificadorOutput, AnalistaOutput, EjecutorOutput, DocumentadorOutput
from agents._resilience import invoke_with_retry, log_fallback, TokenUsageCallback


class _DocumentadorLLMSchema(BaseModel):
    """Esquema de salida estructurada exigido al LLM vía LangChain."""

    reporte_cierre_markdown: str = Field(description="Texto Markdown completo del reporte de cierre.")
    es_nueva_variante: bool = Field(description="True si la combinación de vectores de ataque no corresponde a patrones estándar conocidos.")
    notificar_senior: bool = Field(description="True si se debe notificar a un Analista Senior.")
    resumen_ejecutivo: str = Field(description="Síntesis de 1 párrafo.")


class DocumentadorAgent:
    """Agente Documentador para generación de informes de cierre y detección de variantes."""

    SYSTEM_PROMPT = """Eres el Agente Documentador del sistema ARIA para BBVA.
Tu función es generar el documento formal de cierre de caso e identificar patrones emergentes (Nuevas Variantes de Fraude).

REGLAS DE DOCUMENTACIÓN:
1. Genera un reporte claro en formato Markdown que incluya:
   - Resumen Ejecutivo.
   - Detalle de la Alerta y Atributos Técnicos.
   - Cadena de Razonamiento (CoT) del Pipeline ARIA (Clasificador, Analista, Ejecutor).
   - Acciones Operativas y Recomendaciones de Seguridad.
   El reporte completo (las 4 secciones juntas) debe ser denso pero acotado:
   máximo ~500 palabras en total. NO repitas texto entre 'reporte_cierre_markdown'
   y 'resumen_ejecutivo': el resumen_ejecutivo es una síntesis nueva de 1 párrafo,
   no una copia de la sección "Resumen Ejecutivo" del reporte.

2. Detección de Nueva Variante (HU-2.4.2):
   - Si la combinación de vectores de ataque (ej. RAT + SIM Swapping + Canal no habitual) no corresponde a patrones estándar conocidos, marca 'es_nueva_variante': true y 'notificar_senior': true.
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
            model_kwargs={"temperature": 0.1, "max_tokens": 4500},
        )
        self._structured_llm = self.llm.with_structured_output(_DocumentadorLLMSchema)

    def process(
        self,
        alert: AlertInput,
        clasificacion: ClasificadorOutput,
        analisis: AnalistaOutput,
        ejecucion: EjecutorOutput,
    ) -> DocumentadorOutput:
        """Genera el reporte de cierre a partir de la historia completa del caso."""

        human_prompt = f"""
GENERACIÓN DE INFORME DE CIERRE ARIA:
- Customer ID: {alert.customerid}
- Transacción: Monto ${alert.amount_value:,.2f} COP | Canal {alert.channel} | Servicio {alert.integrationpoint} | Fecha {alert.fecha_transaccion}
- Triage Clasificador: {clasificacion.marcacion_aric}
- Resultado Analista: Final {analisis.clasificacion_final} ({analisis.modus_operandi}) | Confirmado: {analisis.confirmado} | Incertidumbre: {analisis.nivel_incertidumbre}
- Evidencias: {analisis.evidencia}
- Marcación ARIC Ejecutor: {ejecucion.marcacion_aric} | VoiceBot: {ejecucion.disparar_voicebot} | Trazabilidad: {ejecucion.trazabilidad_id}
- Acciones de Contención Sugeridas: {ejecucion.acciones_sugeridas}
- Observación ARIC: {ejecucion.observacion_aric}

Genera el informe técnico de cierre y evalúa si representa una nueva variante de fraude.
"""

        token_cb = TokenUsageCallback()
        try:
            result: _DocumentadorLLMSchema = invoke_with_retry(
                self._structured_llm,
                [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=human_prompt),
                ],
                agent_name="Documentador",
                token_callback=token_cb,
            )

            return DocumentadorOutput(
                reporte_cierre_markdown=result.reporte_cierre_markdown,
                es_nueva_variante=result.es_nueva_variante,
                notificar_senior=result.notificar_senior,
                resumen_ejecutivo=result.resumen_ejecutivo,
                metadata={"customerid": alert.customerid, "trazabilidad_id": ejecucion.trazabilidad_id, "tokens": token_cb.as_dict()},
            )
        except Exception as e:
            # Fallback seguro segun HU-2.4.3: Resiliencia ante fallos de generación
            log_fallback("Documentador", e)
            draft_md = f"""# Borrador de Cierre ARIA (Fallback por Error de Generación)
- **Customer ID**: {alert.customerid}
- **Marcación ARIC**: {ejecucion.marcacion_aric}
- **Tipología Evaluada**: {analisis.clasificacion_final}
- **ID Trazabilidad**: {ejecucion.trazabilidad_id}
- **Nota**: Ocurrió un error en el generador de texto: {str(e)}. Los datos crudos se conservan intactos.
"""
            return DocumentadorOutput(
                reporte_cierre_markdown=draft_md,
                es_nueva_variante=False,
                notificar_senior=False,
                resumen_ejecutivo=f"Caso procesado con marcación {ejecucion.marcacion_aric}. Documentación generada en borrador por fallo técnico.",
                metadata={"error": str(e), "tokens": token_cb.as_dict()},
            )
