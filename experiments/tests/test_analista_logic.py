from agents.analista import _derivar_marcacion_aric


def test_escalamiento_forzado_es_siempre_risk_suspected():
    assert _derivar_marcacion_aric("[NF___FALSO_POSITIVO]", "BAJO", True) == "RISK_SUSPECTED"


def test_incertidumbre_alta_es_siempre_risk_suspected():
    assert _derivar_marcacion_aric("[FR___RAT]", "ALTO", False) == "RISK_SUSPECTED"


def test_taxonomia_fraude_sin_escalamiento_es_risk():
    assert _derivar_marcacion_aric("[FR___SUPLANTACIN]", "BAJO", False) == "RISK"


def test_taxonomia_no_fraude_sin_escalamiento_es_no_risk():
    assert _derivar_marcacion_aric("[NF___DESCARTE]", "MEDIO", False) == "NO_RISK"


def test_taxonomia_sin_prefijo_reconocido_es_conservadora():
    # Una taxonomía alucinada/inválida no debe colarse como NO_RISK: postura
    # conservadora ante lo desconocido.
    assert _derivar_marcacion_aric("[ALGO___RARO]", "BAJO", False) == "RISK_SUSPECTED"


def test_normaliza_corchetes_y_mayusculas():
    assert _derivar_marcacion_aric("fr___rat", "BAJO", False) == "RISK"
