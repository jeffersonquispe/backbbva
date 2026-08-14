"""
Cálculo de costo en USD a partir del consumo de tokens de los agentes ARIA.

Las tarifas viven en pricing.yaml (sí se lee en tiempo de ejecución, a
diferencia de aria_rules.yaml) -> para cambiar un precio o agregar un modelo,
edita ese YAML, no este módulo.
"""
import os
from functools import lru_cache

import yaml

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
PRICING_PATH = os.path.join(_ROOT_DIR, "pricing.yaml")


@lru_cache(maxsize=1)
def _cargar_tarifario() -> dict:
    with open(PRICING_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def obtener_precios(model_id: str = None) -> dict:
    """Devuelve {"input_price": X, "output_price": Y, "label": ...} (USD / 1M tokens)
    para `model_id`. Si el modelo no está en pricing.yaml, cae al `default_model`
    del tarifario en vez de fallar -- un modelo nuevo sin tarifa cargada no debe
    tumbar una corrida ya en curso, solo dar un costo aproximado con la tarifa
    por defecto."""
    tarifario = _cargar_tarifario()
    modelos = tarifario.get("models", {})
    model_id = model_id or tarifario.get("default_model")
    precios = modelos.get(model_id)
    if precios is None:
        precios = modelos.get(tarifario.get("default_model"), {"input_price": 0.0, "output_price": 0.0})
    return precios


def costo_usd(input_tokens: int, output_tokens: int, model_id: str = None) -> float:
    """Costo en USD de `input_tokens` + `output_tokens` para `model_id`."""
    precios = obtener_precios(model_id)
    costo = (input_tokens / 1_000_000) * precios["input_price"] + (output_tokens / 1_000_000) * precios["output_price"]
    return round(costo, 6)


def calcular_costos_por_agente(tokens_por_agente: dict, model_id: str = None) -> dict:
    """A partir de {agente: {input_tokens, output_tokens, total_tokens, llamadas}},
    devuelve la misma estructura de agentes con el costo USD agregado a cada uno,
    más una entrada "_total" con el costo agregado del pipeline completo."""
    resultado = {}
    total = 0.0
    for agente, t in tokens_por_agente.items():
        c = costo_usd(t.get("input_tokens", 0), t.get("output_tokens", 0), model_id)
        resultado[agente] = round(c, 6)
        total += c
    resultado["_total"] = round(total, 6)
    return resultado
