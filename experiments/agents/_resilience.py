"""
Utilidades compartidas de resiliencia para los agentes ARIA: logging visible en
CloudWatch para las rutas de fallback (antes silenciosas) y reintento con
backoff exponencial ante throttling transitorio de Bedrock.

Antes, cualquier error (throttling transitorio incluido) caía directo al
fallback conservador de cada agente sin dejar rastro en los logs, y sin haber
intentado una segunda vez. Bajo carga, eso podía degradar el pipeline entero a
"todo sospechoso" de forma invisible.
"""

import logging
import random
import time

from botocore.exceptions import ClientError
from langchain_core.callbacks.base import BaseCallbackHandler
from pydantic import ValidationError

logger = logging.getLogger("aria.agents")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class TokenUsageCallback(BaseCallbackHandler):
    """Acumula el consumo de tokens de todas las llamadas a Bedrock que pasen
    por esta instancia (incluidos los reintentos fallidos de invoke_with_retry:
    un intento que gasta tokens y falla la validación de Pydantic igual costó
    esos tokens, así que cuentan)."""

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.llamadas = 0

    def on_llm_end(self, response, **kwargs):
        self.llamadas += 1
        for generation_list in getattr(response, "generations", []) or []:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) if message else None
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0) or 0
                    self.output_tokens += usage.get("output_tokens", 0) or 0
                    self.total_tokens += usage.get("total_tokens", 0) or 0

    def as_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "llamadas": self.llamadas,
        }

# Códigos de error de Bedrock/AWS que representan una condición transitoria:
# reintentar tiene sentido.
_RETRYABLE_ERROR_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "InternalServerException",
}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        return code in _RETRYABLE_ERROR_CODES
    if isinstance(exc, ValidationError):
        # El modelo no devolvió una llamada de herramienta válida (ej. dict
        # vacío: "Field required [type=missing]"), o devolvió un valor fuera
        # del set cerrado (ej. taxonomía inventada). Reintentar es seguro en
        # ambos casos: en el primero le da al modelo otra oportunidad de
        # responder bien; en el segundo, si vuelve a fallar, sigue cayendo al
        # fallback exactamente igual que antes — nunca se acepta un valor
        # inválido en silencio, solo se le da una segunda oportunidad de
        # acertar antes de rendirse.
        return True
    return False


def invoke_with_retry(structured_llm, messages, agent_name: str, max_retries: int = 3,
                       base_delay: float = 1.0, token_callback: "TokenUsageCallback | None" = None):
    """Invoca `structured_llm.invoke(messages)` reintentando ante fallos
    transitorios. Cualquier otro error se propaga en el primer intento, para
    que el agente caiga a su fallback seguro sin demora.

    El delay entre intentos depende del tipo de error: un throttling de
    Bedrock necesita backoff exponencial (darle tiempo a AWS a liberar
    capacidad); un ValidationError de Pydantic (el modelo no devolvió una
    llamada de herramienta válida) no necesita esperar nada — es solo pedirle
    al modelo una nueva muestra — así que usa un delay corto y fijo para no
    comerse el SLA de 5-10s de estos agentes.

    Si se pasa `token_callback`, se reutiliza la misma instancia en cada
    intento (exitoso o no), así que acumula el consumo real de tokens de todo
    el proceso de reintento, no solo del intento que finalmente tuvo éxito."""
    config = {"callbacks": [token_callback]} if token_callback is not None else None
    attempt = 0
    while True:
        try:
            return structured_llm.invoke(messages, config=config)
        except Exception as e:
            attempt += 1
            if not _is_retryable(e) or attempt > max_retries:
                logger.error(
                    "[%s] fallo tras %d intento(s), no se reintenta más: %s",
                    agent_name, attempt, e,
                )
                raise
            if isinstance(e, ValidationError):
                delay = 0.2 + random.uniform(0, 0.2)
            else:
                delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "[%s] error transitorio (intento %d/%d), reintentando en %.1fs: %s",
                agent_name, attempt, max_retries, delay, e,
            )
            time.sleep(delay)


def log_fallback(agent_name: str, error: Exception) -> None:
    """Deja constancia visible en logs (CloudWatch) de que un agente cayó a su
    fallback seguro, en vez de que el error solo viva en el `metadata` de la
    respuesta JSON."""
    logger.error("[%s] cayó a fallback seguro por: %s", agent_name, error)
