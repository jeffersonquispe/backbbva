"""
Script Interactivo para Probar los Agentes ARIA (Localmente o en AWS Lambda).
Muestra un menú para probar cada agente individualmente o el pipeline completo.
"""

import sys
import os
import json

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lambda_function import lambda_handler

ALERT_EJEMPLO = {
    "customerid": "8614703",
    "marcacion_final": "risk-suspected",
    "razon_marcacion": "[FR___NO_HABITO_TRXS]",
    "eventtype": "paymentRT",
    "channel": "GL",
    "integrationpoint": "SMGG20210247 - postIdentityDocumentTransfers",
    "biocatch_score": 930.0,
    "Model_score": 84465.0,
    "amount_value": 3000000.0,
    "fecha_transaccion": "2026-07-10 11:32:46.000",
    "biocatch_isMobileRat": 0,
    "biocatch_isEmulator": 0,
    "biocatch_isRat": 0,
    "biocatch_isBot": 0,
    "MontoMasAltoGlomo": 10000000.0,
    "MontoMasAltoBreB": 10000000.0
}

def probar_modo(mode_name: str):
    print(f"\n========================================================")
    print(f"🚀 PROBANDO AGENTE ARIA EN MODO: {mode_name.upper()}")
    print(f"========================================================")
    
    event = {
        "mode": mode_name,
        "alert": ALERT_EJEMPLO
    }
    
    res = lambda_handler(event)
    if res["statusCode"] == 200:
        data = json.loads(res["body"])
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("❌ Error:", res["body"])

def main():
    print("=== SUITE DE PRUEBAS INTERACTIVA - AGENTES ARIA ===")
    print("1. Probar Pipeline E2E Completo (Clasificador -> Analista -> Ejecutor -> Documentador)")
    print("2. Probar SOLO Agente Clasificador (HU-2.1.x)")
    print("3. Probar SOLO Agente Analista (HU-2.2.x)")
    print("4. Probar SOLO Agente Ejecutor (HU-2.3.x)")
    print("5. Salir")
    
    # Si viene argumento por CLI (ej: python test_agent_interactive.py 1)
    if len(sys.argv) > 1:
        opcion = sys.argv[1]
    else:
        opcion = "1" # Por defecto ejecuta pipeline completo
        
    if opcion == "1":
        probar_modo("pipeline")
    elif opcion == "2":
        probar_modo("clasificador")
    elif opcion == "3":
        probar_modo("analista")
    elif opcion == "4":
        probar_modo("ejecutor")
    else:
        print("Saliendo de la prueba.")

if __name__ == "__main__":
    main()
