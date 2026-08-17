"""
Agente de Perfilamiento ARIA (HU-2.0.1 a HU-2.0.5).
Traduce los campos crudos de una alerta transaccional a descripciones en lenguaje
natural (perfil de usuario, de transacción, histórico e hipótesis de sospecha)
que sirven como input semántico principal para el Agente Clasificador.
"""

import os
from typing import Optional

from pydantic import BaseModel, Field
from langchain_aws import ChatBedrock
from langchain_core.messages import SystemMessage, HumanMessage

from schemas import AlertInput, PerfilamientoOutput
from agents._resilience import invoke_with_retry, log_fallback, TokenUsageCallback
from agents._risk_scales import format_biocatch, format_model_score


class _PerfilamientoLLMSchema(BaseModel):
    """Esquema de salida estructurada exigido al LLM vía LangChain (with_structured_output)."""

    perfil_usuario: str = Field(
        description=(
            "Descripción narrativa del cliente: antigüedad, vínculo, ubicación y "
            "disponibilidad de datos de contacto. Los datos no disponibles se "
            "declaran explícitamente, nunca se inventan ni se omiten en silencio."
        )
    )
    perfil_transaccion: str = Field(
        description=(
            "Descripción narrativa de la transacción evaluada: canal/servicio en "
            "términos de negocio (no códigos crudos), monto contextualizado contra "
            "los techos históricos del cliente, y momento en que ocurrió."
        )
    )
    perfil_historico: str = Field(
        description=(
            "Resumen narrativo del comportamiento reciente de la cuenta (frecuencia, "
            "canales habituales, rango de montos habitual), o declaración explícita "
            "de que no hay historial disponible (Cold Start)."
        )
    )
    hipotesis_sospecha: str = Field(
        description=(
            "Deducción de por qué la alerta podría ser sospechosa o no, citando qué "
            "señales concretas la sustentan, con una calificación cualitativa de la "
            "fuerza de la señal (débil/moderada/fuerte). NO debe asignar ninguna "
            "taxonomía FCP final: esa decisión es exclusiva del Agente Clasificador."
        )
    )


class PerfiladorAgent:
    """Agente de Perfilamiento: convierte una alerta cruda en lenguaje natural filtrado de ruido."""

    # Tope de transacciones crudas embebidas en el prompt: clientes con
    # historiales largos (vistos hasta ~240 transacciones) inflan tanto el
    # input que el LLM termina gastando su presupuesto de max_tokens narrando
    # el historial y trunca el JSON estructurado antes de llegar al último
    # campo (hipotesis_sospecha). El conteo real siempre se reporta al LLM;
    # solo se recortan las transacciones menos recientes del prompt.
    MAX_HISTORIAL_TXS_EN_PROMPT = 30

    SYSTEM_PROMPT = """Eres el Agente de Perfilamiento del sistema ARIA para BBVA.
Tu única función es TRADUCIR los datos crudos de una alerta transaccional a lenguaje
natural, en términos semánticos, con el ruido de formato completamente filtrado.

REGLAS OBLIGATORIAS:
1. NO clasifiques la alerta ni asignes ninguna taxonomía FCP. Esa decisión es
   exclusiva del Agente Clasificador.
2. NO inventes datos. Si un campo no está disponible, decláralo explícitamente
   ("dato no disponible"), nunca lo omitas en silencio ni lo asumas.
3. NO uses nombres de campos técnicos (ej. no escribas 'biocatch_isRat=1');
   tradúcelos a lenguaje de negocio (ej. "se detectó actividad compatible con
   herramienta de acceso remoto").
4. Filtra el ruido de formato: no repitas notación científica, IDs crudos, ni
   JSON sin procesar.
5. Contextualiza montos y comportamiento en términos relativos, no solo cifras
   aisladas.
6. Sé conciso: cada campo de salida debe tener como máximo 3-4 oraciones.
7. Los scores Biocatch y Featurespace ARIC ya vienen acompañados de su banda
   de riesgo oficial (BAJO/MEDIO/ALTO) calculada según los umbrales de cada
   proveedor. Usa esa banda como la interpretación autorizada del score — NO
   la reinterpretes con tu propio criterio ni la califiques de "escala no
   especificada": si el dato dice RIESGO ALTO, trátalo como una señal fuerte
   en 'hipotesis_sospecha', no como algo ambiguo que el Clasificador deba
   resolver después.
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
            model_kwargs={"temperature": 0.1, "max_tokens": 1800},
        )
        self._structured_llm = self.llm.with_structured_output(_PerfilamientoLLMSchema)

    def process(self, alert: AlertInput) -> PerfilamientoOutput:
        """Genera las descripciones semánticas de la alerta a partir de sus campos crudos."""
        is_cold_start = alert.is_cold_start()
        recent_txs = alert.get_recent_transactions()

        # `recent_txs` viene ordenado del más reciente al más antiguo (ver
        # transacciones_json en el dataset), así que recortar el prefijo
        # conserva las transacciones más relevantes para el perfilamiento.
        historial_para_prompt = recent_txs[: self.MAX_HISTORIAL_TXS_EN_PROMPT]
        historial_truncado_nota = (
            f", mostrando las {self.MAX_HISTORIAL_TXS_EN_PROMPT} más recientes"
            if len(recent_txs) > self.MAX_HISTORIAL_TXS_EN_PROMPT
            else ""
        )

        human_prompt = f"""
DATOS CRUDOS DE LA ALERTA (tradúcelos a lenguaje natural, no los repitas tal cual):

Cliente:
- ID: {alert.customerid}
- Documento: {alert.tipo_documento or 'dato no disponible'} {alert.numero_documento or ''}
- Ciudad: {alert.ciudad or 'dato no disponible'}
- Fecha de alta: {alert.fecha_alta or 'dato no disponible'}
- Cliente revinculado: {'sí' if alert.indicador_revinculado else 'no'}
- Empleado del banco: {'sí' if alert.empleado_banco else 'no'}
- Celular registrado: {'disponible' if alert.celular else 'no disponible'}
- Correo registrado: {'disponible' if (alert.correo_1 or alert.correo_2) else 'no disponible'}

Transacción evaluada:
- Evento / Canal / Servicio: {alert.eventtype} | {alert.channel} | {alert.integrationpoint}
- Monto: ${alert.amount_value:,.2f} COP
- Fecha: {alert.fecha_transaccion}
- Techos históricos por canal: PSE=${alert.MontoMasAltoPSE:,.2f}, Pasarela=${alert.MontoMasAltoPasarelaPago:,.2f}, BreB=${alert.MontoMasAltoBreB:,.2f}, Glomo=${alert.MontoMasAltoGlomo:,.2f}, Net=${alert.MontoMasAltoNet:,.2f}, Préstamo=${alert.MontoMasAltoPrestamo:,.2f}, Retiro tarjeta=${alert.MontoMasAltoRetirosTarjeta:,.2f}

Señales de riesgo:
- Score Biocatch: {format_biocatch(alert.biocatch_score)}
- Score Modelo Featurespace ARIC: {format_model_score(alert.Model_score)}
- Banderas Biocatch: MobileRAT={bool(alert.biocatch_isMobileRat)}, Emulator={bool(alert.biocatch_isEmulator)}, RAT={bool(alert.biocatch_isRat)}, Bot={bool(alert.biocatch_isBot)}

Historial reciente ({len(recent_txs)} transacciones totales, Cold Start={is_cold_start}{historial_truncado_nota}):
{historial_para_prompt if historial_para_prompt else 'sin historial reciente disponible'}

Genera los 4 campos del perfilamiento a partir de esta información.
"""

        token_cb = TokenUsageCallback()
        try:
            result: _PerfilamientoLLMSchema = invoke_with_retry(
                self._structured_llm,
                [
                    SystemMessage(content=self.SYSTEM_PROMPT),
                    HumanMessage(content=human_prompt),
                ],
                agent_name="Perfilador",
                token_callback=token_cb,
            )

            texto_consolidado = (
                f"PERFIL DE USUARIO: {result.perfil_usuario}\n\n"
                f"PERFIL DE TRANSACCIÓN: {result.perfil_transaccion}\n\n"
                f"PERFIL HISTÓRICO: {result.perfil_historico}\n\n"
                f"HIPÓTESIS DE SOSPECHA: {result.hipotesis_sospecha}"
            )

            return PerfilamientoOutput(
                perfil_usuario=result.perfil_usuario,
                perfil_transaccion=result.perfil_transaccion,
                perfil_historico=result.perfil_historico,
                hipotesis_sospecha=result.hipotesis_sospecha,
                texto_consolidado=texto_consolidado,
                metadata={"customerid": alert.customerid, "cold_start": is_cold_start, "tokens": token_cb.as_dict()},
            )
        except Exception as e:
            # Fallback seguro segun HU-2.0.5: sin inventar texto, solo lo derivable
            # determinísticamente de AlertInput.
            log_fallback("Perfilador", e)
            perfil_usuario_fallback = (
                f"Cliente {alert.customerid}. Datos ampliados no disponibles por error técnico."
            )
            perfil_transaccion_fallback = (
                f"Transacción por ${alert.amount_value:,.2f} COP en el servicio "
                f"{alert.integrationpoint}, canal {alert.channel}, evento {alert.eventtype}."
            )
            perfil_historico_fallback = (
                "Cliente sin historial reciente disponible."
                if is_cold_start
                else f"Se registran {len(recent_txs)} transacciones recientes (no resumidas por error técnico)."
            )
            hipotesis_fallback = f"No fue posible generar la hipótesis de sospecha: {str(e)}"
            texto_consolidado_fallback = (
                f"{perfil_usuario_fallback}\n{perfil_transaccion_fallback}\n"
                f"{perfil_historico_fallback}\n{hipotesis_fallback}"
            )

            return PerfilamientoOutput(
                perfil_usuario=perfil_usuario_fallback,
                perfil_transaccion=perfil_transaccion_fallback,
                perfil_historico=perfil_historico_fallback,
                hipotesis_sospecha=hipotesis_fallback,
                texto_consolidado=texto_consolidado_fallback,
                metadata={"error": str(e), "tokens": token_cb.as_dict()},
            )
