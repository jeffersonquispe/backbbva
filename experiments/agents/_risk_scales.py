"""
Umbrales de riesgo oficiales para las señales instrumentales de ARIA
(BioCatch y el modelo Featurespace ARIC).

Ningún prompt documentaba estos umbrales antes: los agentes recibían el
número crudo y tenían que adivinar si era "alto" o "bajo", lo que producía
lecturas inconsistentes de caso a caso (ver hallazgos del piloto blind test
sobre Muestra_200_ARIA_balanceada.csv). La banda se calcula acá de forma
determinística y se inyecta ya resuelta en el prompt, en vez de pedirle al
LLM que aplique la tabla de umbrales por su cuenta.

biocatch_score: escala 0-1000 tal como la documenta BioCatch, y los valores
observados en el dataset caen dentro de ese rango.
    0-399   Riesgo Bajo (comportamiento genuino)
    400-799 Riesgo Medio (revisión / MFA)
    800-1000 Riesgo Alto (alerta crítica / bloqueo)

Model_score (Featurespace ARIC): la documentación oficial usa escala 0-1000
(bajo 0-599, medio 600-849, alto 850-1000), pero los valores reales en este
dataset están en escala 0-1 (probabilidad), con -1.0 como centinela de
"no aplica" para eventos donde Featurespace no corre (ver eventtype). Se
usan los mismos cortes oficiales reescalados /1000 para no perder el
sentido de la banda: 0-0.599 bajo, 0.600-0.849 medio, 0.850-1.000 alto.
"""

from typing import Optional

BIOCATCH_UMBRAL_MEDIO = 400
BIOCATCH_UMBRAL_ALTO = 800

MODEL_SCORE_NO_APLICA_CENTINELA = -1.0
MODEL_SCORE_UMBRAL_MEDIO = 0.600
MODEL_SCORE_UMBRAL_ALTO = 0.850


def biocatch_risk_band(score: Optional[float]) -> Optional[str]:
    """BAJO/MEDIO/ALTO según umbrales oficiales BioCatch (escala 0-1000), o None si no hay score."""
    if score is None:
        return None
    if score >= BIOCATCH_UMBRAL_ALTO:
        return "ALTO"
    if score >= BIOCATCH_UMBRAL_MEDIO:
        return "MEDIO"
    return "BAJO"


def model_score_risk_band(score: Optional[float]) -> Optional[str]:
    """BAJO/MEDIO/ALTO según umbrales Featurespace reescalados a 0-1, o None si no aplica/no hay score."""
    if score is None or score == MODEL_SCORE_NO_APLICA_CENTINELA or score < 0:
        return None
    if score >= MODEL_SCORE_UMBRAL_ALTO:
        return "ALTO"
    if score >= MODEL_SCORE_UMBRAL_MEDIO:
        return "MEDIO"
    return "BAJO"


def format_biocatch(score: Optional[float]) -> str:
    band = biocatch_risk_band(score)
    if band is None:
        return "no aplica para este canal/tipo de evento"
    return f"{score:.0f} (banda oficial BioCatch: RIESGO {band})"


def format_model_score(score: Optional[float]) -> str:
    band = model_score_risk_band(score)
    if band is None:
        return "no aplica para este canal/tipo de evento"
    return f"{score:.3f} (banda oficial Featurespace ARIC: RIESGO {band})"
