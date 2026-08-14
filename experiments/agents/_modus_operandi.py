"""
Catálogo de Modus Operandi (MO) y motor de reglas duras de ARIA.

Fuente: matriz de decisión de fraude transaccional bancario (ARIC, Biocatch,
Veridas DVS, 3270) -- la misma taxonomía de 6 MO que usa un analista humano de
monitoreo de fraude, mapeada acá a las 10 taxonomías FCP cerradas que ya usa el
sistema (ver agents/_taxonomia.py) para no crear un segundo catálogo paralelo.

Dos usos:
1. `evaluar_reglas_duras()`: filtros previos DETERMINÍSTICOS (sin LLM) que se
   corren antes del pipeline de agentes -- exactamente igual en espíritu a
   agents/_risk_scales.py (bandas de score) o agents/_marcacion.py (derivación
   de marcación): si el dato ya es inequívoco, no tiene sentido pagarle una
   llamada a Bedrock ni arriesgarse a que el LLM lo interprete distinto cada
   vez. Ver lambda_function.py, modo "pipeline".
2. `MODUS_OPERANDI_POR_TAXONOMIA`: conocimiento de referencia (señales típicas +
   acciones de contención) que se inyecta en los prompts de Clasificador,
   Analista y Ejecutor -- el "playbook" que un analista humano ya trae en la
   cabeza y que hoy el LLM tiene que reconstruir caso a caso desde cero.

Campos que la fuente original menciona pero que NO existen en los 43 campos del
dataset sintético actual (Campos_prueba) quedan documentados pero inactivos:
  - `dg_hurto` (nombre de regla ARIC): no hay un campo "regla disparada" crudo,
    solo se puede usar el datapoint equivalente `biocatch_indrobo1`.
  - `isRecentRat`: no existe distinto de `biocatch_isRat`.
  - UserAgent/IMEI (cambio de dispositivo), Veridas DVS, franja horaria vs.
    hábito real: no hay campos crudos para calcularlos de forma determinística
    hoy -- quedan como señales narrativas que el LLM evalúa con el texto del
    Perfilador, igual que ya hace con "contraparte nueva" o "vaciamiento
    progresivo" (ver agents/clasificador.py, regla 5).
"""

from typing import Any, Dict, List, Optional

# ------------------------------------------------------------------------------
# Catálogo de referencia: señales típicas + acciones de contención por taxonomía
# FCP. Los MO de la fuente que no calzan 1 a 1 con una taxonomía (ATO / Vishing
# / SIM Swap comparten features) se repiten en las taxonomías más cercanas --
# es una guía de razonamiento para el LLM, no una regla de negocio estricta.
# ------------------------------------------------------------------------------
MODUS_OPERANDI_POR_TAXONOMIA: Dict[str, Dict[str, Any]] = {
    "[FR___SUPLANTACIN]": {
        "nombre": "Suplantación de Identidad (Onboarding / Cliente Existente)",
        "senales": [
            "Antigüedad de cuenta < 6 meses, o revinculado reciente",
            "Inconsistencia en verificación biométrica/documental (Veridas DVS)",
            "Agotamiento de saldo/cupo o uso de crédito inmediato tras vinculación",
            "Modificación reciente de datos de contacto (teléfono/email) seguida de operación",
        ],
        "acciones": ["Bloqueo Cuenta", "Baja Softoken", "Bloqueo Hard GLOMO/NET", "Bloqueo Tarjeta", "BAEP Blacklist"],
    },
    "[FR___SIM_SWAPPING]": {
        "nombre": "Account Takeover (ATO) / SIM Swap",
        "senales": [
            "Cambio de dispositivo o SIM detectado poco antes de la transacción",
            "Enrolamiento de Softoken reciente en dispositivo nuevo",
            "Transacción fuera de hábito (monto o destinatario no usual) tras el enrolamiento",
        ],
        "acciones": ["Baja Softoken", "Bloqueo Soft GLOMO", "Bloqueo NET (si hubo cambio de clave)"],
    },
    "[FR___VISHING]": {
        "nombre": "Estafa / Ingeniería Social",
        "senales": [
            "Dispositivo y credenciales habituales del cliente (sin anomalía técnica)",
            "Biometría/OTP legítimos del titular real",
            "Transacción fuera de hábito hacia contraparte nueva, monedero, o bajo llamada activa",
        ],
        "acciones": [
            "Bloqueo Soft GLOMO",
            "Baja Softoken",
            "Enviar a Voicebot/Asesor -- alertar sobre el riesgo del destino, NUNCA preguntar si el cliente 'reconoce' la operación (el titular real la está autorizando bajo engaño)",
        ],
    },
    "[FR___RAT]": {
        "nombre": "Malware / RAT APK",
        "senales": ["isRat / isMobileRat / isBot activos", "Manipulación remota de sesión móvil"],
        "acciones": ["Baja Softoken", "Bloqueo Hard de Canal"],
    },
    "[FR___MALWARE]": {
        "nombre": "Malware / RAT APK",
        "senales": ["Infección de malware en dispositivo detectada por Biocatch/ARIC"],
        "acciones": ["Baja Softoken", "Bloqueo Hard de Canal"],
    },
    "[FR___PHARMING]": {
        "nombre": "Pharming / Redirección Maliciosa",
        "senales": ["Redirección de tráfico o DNS maliciosa detectada"],
        "acciones": ["Bloqueo Hard de Canal", "Baja Softoken"],
    },
    "[FR___NO_HABITO_TRXS]": {
        "nombre": "Pérdida / Robo / Cambiazo de Tarjeta",
        "senales": [
            "Transacción presencial (POS chip/contactless o ATM) fuera de patrón geográfico",
            "Sin hábito transaccional en ese comercio o franja horaria",
        ],
        "acciones": ["Bloqueo Tarjeta (apagado preventivo o bloqueo definitivo)"],
    },
    "[NF___FALSO_POSITIVO]": {
        "nombre": "Transacción Genuina",
        "senales": [
            "Credenciales y dispositivo habituales",
            "Historial de transacciones aprobadas al mismo destino/módulo",
            "Dentro de montos históricos máximos y horario hábil (06:00-20:00)",
        ],
        "acciones": [],
    },
    "[NF___ANLISIS]": {
        "nombre": "Operación Normal Descartable",
        "senales": ["Revisión rápida sin ninguna señal de riesgo relevante"],
        "acciones": [],
    },
    "[NF___DESCARTE]": {
        "nombre": "Descarte por Regla Automática",
        "senales": ["Cumple una regla de descarte predefinida del negocio"],
        "acciones": [],
    },
}


def acciones_por_taxonomia(taxonomia: Optional[str]) -> List[str]:
    """Bloqueos sugeridos para la taxonomía FCP definitiva (la del Analista)."""
    entrada = MODUS_OPERANDI_POR_TAXONOMIA.get(taxonomia or "")
    return list(entrada["acciones"]) if entrada else []


def modus_operandi_por_taxonomia(taxonomia: Optional[str]) -> str:
    """Nombre de MO legible para la taxonomía FCP definitiva."""
    entrada = MODUS_OPERANDI_POR_TAXONOMIA.get(taxonomia or "")
    return entrada["nombre"] if entrada else "Sin MO asociado"


def catalogo_como_texto() -> str:
    """Bloque de referencia para inyectar en los prompts de Clasificador/Analista/
    Ejecutor: señales típicas y acciones por taxonomía, en un formato compacto."""
    lineas = []
    for taxonomia, info in MODUS_OPERANDI_POR_TAXONOMIA.items():
        senales = "; ".join(info["senales"]) if info["senales"] else "sin señales distintivas"
        acciones = ", ".join(info["acciones"]) if info["acciones"] else "ninguna (no amerita bloqueo)"
        lineas.append(f"   - {taxonomia} ({info['nombre']}): señales típicas: {senales}. Acciones: {acciones}.")
    return "\n".join(lineas)


# ------------------------------------------------------------------------------
# Reglas duras: filtros previos determinísticos, antes de invocar cualquier LLM.
# ------------------------------------------------------------------------------

_SEGMENTOS_BANCA_PRIVADA = {"WEALTH", "PREMIUM_VIP"}


def evaluar_reglas_duras(alert) -> Optional[Dict[str, Any]]:
    """Devuelve un veredicto determinístico completo (marcacion_aric, MO, acciones,
    justificación) si se cumple alguna regla dura de exclusión o disparo directo,
    o None si el caso debe seguir el pipeline normal (Clasificador -> Analista ->
    Ejecutor). `alert` es un `schemas.AlertInput`; se tipa como Any acá para
    evitar un import circular con schemas.py (que no depende de agents/)."""

    # 1) Cliente Wealth / Premium VIP: derivar al circuito de banca privada, SIN
    # aplicar bloqueos automáticos masivos. No es un veredicto de fraude -- es una
    # regla de ruteo que tiene prioridad sobre cualquier otra señal.
    if getattr(alert, "segmento", None) and str(alert.segmento).strip().upper() in _SEGMENTOS_BANCA_PRIVADA:
        return {
            "regla": "SEGMENTO_BANCA_PRIVADA",
            "marcacion_aric": "RISK_SUSPECTED",
            "modus_operandi": "N/A -- Circuito Banca Privada / Wealth",
            # Sin taxonomía FCP real: no es un veredicto de fraude, es una regla de ruteo.
            "taxonomia_referencial": None,
            "cot_justificacion": (
                f"Segmento de cliente '{alert.segmento}' -- derivado al circuito exclusivo de banca "
                "privada/wealth para revisión manual, sin aplicar bloqueos automáticos masivos."
            ),
            "acciones_sugeridas": [],
            "disparar_voicebot": False,
        }

    # 2) Disparador directo de hurto (Biocatch indRobo1). El nombre de regla ARIC
    # "dg_hurto" no existe como campo crudo en el dataset sintético actual -- solo
    # se evalúa el datapoint equivalente que sí está disponible.
    if getattr(alert, "biocatch_indrobo1", 0):
        return {
            "regla": "INDROBO1",
            "marcacion_aric": "RISK",
            "modus_operandi": "Hurto de Celular / Paseo Millonario",
            # Taxonomía FCP más cercana -- el catálogo cerrado no tiene una categoría
            # específica para "hurto físico con coacción", así que se reporta bajo la
            # más próxima (desviación abrupta de patrón por compromiso físico).
            "taxonomia_referencial": "[FR___NO_HABITO_TRXS]",
            "cot_justificacion": "biocatch_indrobo1 activo -- indicador directo de hurto/sustancias, regla dura sin pasar por triage LLM.",
            "acciones_sugeridas": ["Baja Softoken", "Bloqueo Soft GLOMO", "Bloqueo Tarjeta Débito/Crédito"],
            "disparar_voicebot": False,
        }

    # 3) Disparador directo de malware/RAT (Biocatch). `isRecentRat` de la fuente
    # original no existe distinto de `isRat` en este dataset.
    if getattr(alert, "biocatch_isRat", 0) or getattr(alert, "biocatch_isMobileRat", 0) or getattr(alert, "biocatch_isBot", 0):
        return {
            "regla": "MALWARE_RAT_BOT",
            "marcacion_aric": "RISK",
            "modus_operandi": "Malware / RAT APK",
            "taxonomia_referencial": "[FR___RAT]",
            "cot_justificacion": "Señal de RAT/Bot activa (isRat/isMobileRat/isBot) -- indicador directo de malware, regla dura sin pasar por triage LLM.",
            "acciones_sugeridas": ["Baja Softoken", "Bloqueo Hard de Canal"],
            "disparar_voicebot": False,
        }

    return None


def formatear_observacion_aric(
    taxonomia: str,
    canal: str,
    habito: Optional[bool],
    resumen: str,
    dispositivo: Optional[bool] = None,
) -> str:
    """Observación estandarizada de una línea para pegar en ARIC:
    "[MO: <TAXONOMIA>] [CANAL: <CANAL>] [HABITO: SI/NO/N-D] [DISP: HABITUAL/NUEVO/N-D] - <resumen>"

    `dispositivo` queda casi siempre en None: el dataset sintético no trae
    UserAgent/IMEI, así que no hay forma honesta de afirmar "habitual" o "nuevo"
    -- se reporta N-D (no disponible) en vez de inventar una lectura.
    """
    habito_txt = "N-D" if habito is None else ("SI" if habito else "NO")
    disp_txt = "N-D" if dispositivo is None else ("HABITUAL" if dispositivo else "NUEVO")
    resumen_una_linea = " ".join(str(resumen).split())
    return f"[MO: {taxonomia}] [CANAL: {canal}] [HABITO: {habito_txt}] [DISP: {disp_txt}] - {resumen_una_linea}"
