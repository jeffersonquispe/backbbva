"""
Derivación determinística de la marcación de riesgo ARIC (RISK / NO_RISK /
RISK_SUSPECTED) a partir de una taxonomía FCP + señal de incertidumbre.

Compartida por Clasificador y Analista (agents/clasificador.py,
agents/analista.py): la evaluación sin GT mostró que un LLM no respeta un set
cerrado de 3 taxonomías el 80% de las veces (ver docs/HU-Perfilamiento.md), así
que en vez de pedirle esta marcación directamente a cada agente, los dos
declaran su propia taxonomía FCP + nivel_incertidumbre/requiere_escalamiento, y
esta regla de prefijo se aplica en código sobre esos campos.
"""


def derivar_marcacion_aric(clasificacion: str, nivel_incertidumbre: str, requiere_escalamiento: bool) -> str:
    """RISK_SUSPECTED si hay escalamiento o incertidumbre ALTA; si no, RISK para
    prefijo FR___, NO_RISK para NF___, y RISK_SUSPECTED (postura conservadora)
    si el prefijo no se reconoce (taxonomía inválida/alucinada)."""
    if requiere_escalamiento or str(nivel_incertidumbre).upper() == "ALTO":
        return "RISK_SUSPECTED"
    normalizado = str(clasificacion).strip("[]").upper()
    if normalizado.startswith("FR___"):
        return "RISK"
    if normalizado.startswith("NF___"):
        return "NO_RISK"
    return "RISK_SUSPECTED"
