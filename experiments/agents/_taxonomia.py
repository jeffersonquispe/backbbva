"""
Catálogo cerrado de taxonomías FCP.

Antes vivía en agents/clasificador.py porque el Clasificador era quien debía
elegir una de estas 10 categorías como su salida oficial (RULE-CLA-01 en su
versión anterior). Ahora el Clasificador decide directamente marcacion_aric
(RISK/NO_RISK/RISK_SUSPECTED, ver agents/clasificador.py) y usa este catálogo
solo como conocimiento de referencia dentro del prompt -- quien sigue
asignando la taxonomía FCP oficial es el Analista (AnalistaOutput.clasificacion_final).
"""

from typing import Literal

TAXONOMIAS_PERMITIDAS = [
    "[FR___NO_HABITO_TRXS]",
    "[FR___SUPLANTACIN]",
    "[FR___RAT]",
    "[FR___VISHING]",
    "[FR___MALWARE]",
    "[FR___PHARMING]",
    "[FR___SIM_SWAPPING]",
    "[NF___FALSO_POSITIVO]",
    "[NF___ANLISIS]",
    "[NF___DESCARTE]",
]

# Set cerrado forzado a nivel de schema donde se necesite (hoy: AnalistaOutput):
# un valor fuera de estos 10 falla la validación de Pydantic en vez de aceptarse
# en silencio.
_TaxonomiaFCP = Literal[tuple(TAXONOMIAS_PERMITIDAS)]  # type: ignore[valid-type]

# Descripciones de referencia -- el "playbook" de señales típicas por taxonomía,
# usado como contexto de razonamiento en el prompt del Clasificador (no como un
# campo que tenga que llenar). Mantiene en un solo lugar lo que antes vivía
# repetido/disperso en las reglas del system prompt.
TAXONOMIAS_DESCRIPCION = {
    "[FR___NO_HABITO_TRXS]": "Desviación abrupta del patrón o canal habitual.",
    "[FR___SUPLANTACIN]": "Indicios de toma de cuenta (Account Takeover) o datos falsos.",
    "[FR___RAT]": "Herramienta de acceso remoto o manipulación móvil activa.",
    "[FR___VISHING]": "Ingeniería social por voz o engaño telefónico.",
    "[FR___MALWARE]": "Infección por software malicioso en dispositivo.",
    "[FR___PHARMING]": "Redirección maliciosa de tráfico o DNS.",
    "[FR___SIM_SWAPPING]": "Duplicación no autorizada de tarjeta SIM.",
    "[NF___FALSO_POSITIVO]": "Transacción legítima del usuario habitual.",
    "[NF___ANLISIS]": "Operación normal descartable tras revisión rápida.",
    "[NF___DESCARTE]": "Regla automática de descarte predefinida.",
}
