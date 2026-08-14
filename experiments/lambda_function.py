"""
AWS Lambda Handler Entrypoint para los Agentes ARIA (BBVA Fraude).
Orquesta la ejecución de Perfilador, Clasificador, Analista, Ejecutor y Documentador
consumiendo Claude Sonnet 4.6 en Bedrock vía LangChain.
"""

import json
import time
import os
import uuid
from typing import Dict, Any

from schemas import AlertInput, ClasificadorOutput, AnalistaOutput, EjecutorOutput
from agents import PerfiladorAgent, ClasificadorAgent, AnalistaAgent, EjecutorAgent, DocumentadorAgent
from agents._modus_operandi import evaluar_reglas_duras, formatear_observacion_aric

# Instanciados a nivel de modulo (no dentro del handler) para que AWS Lambda
# los reutilice entre invocaciones de un mismo contexto de ejecucion "caliente".
# Cada uno crea su propio cliente ChatBedrock/boto3 en __init__; recrearlos en
# cada llamada (como antes) desperdiciaba esa inicializacion en cada invocacion,
# incluso en modos que no usan los 5 agentes.
perfilador = PerfiladorAgent()
clasificador = ClasificadorAgent()
analista = AnalistaAgent()
ejecutor = EjecutorAgent()
documentador = DocumentadorAgent()


def lambda_handler(event: Dict[str, Any], context: Any = None) -> Dict[str, Any]:
    """Handler oficial AWS Lambda.
    
    Estructura esperada en `event`:
    {
      "mode": "pipeline" | "clasificador" | "analista" | "ejecutor" | "documentador",
      "alert": { ... 43 campos sintéticos de Campos_prueba / Muestra ... }
    }
    """
    start_time = time.time()
    
    # 1. Parsear el evento de entrada
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except Exception:
            pass
            
    # Si viene desde API Gateway HTTP Proxy, parsear 'body'
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            try:
                body = json.loads(body)
            except Exception:
                body = {}
        alert_data = body.get("alert", body)
        mode = body.get("mode", "pipeline")
    else:
        alert_data = event.get("alert", event)
        mode = event.get("mode", "pipeline")

    if not isinstance(alert_data, dict) or not alert_data:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Payload de alerta inválido o no provisto."})
        }

    # 2. Inicializar Alerta
    alert = AlertInput.from_dict(alert_data)

    # 3. Los agentes ya están instanciados a nivel de módulo (ver arriba).

    response_payload: Dict[str, Any] = {
        "customerid": alert.customerid,
        "mode": mode,
        "status": "SUCCESS"
    }

    try:
        if mode == "perfilador":
            out_perf = perfilador.process(alert)
            response_payload["perfilamiento"] = out_perf.to_dict()

        elif mode == "clasificador":
            out_perf = perfilador.process(alert)
            out_clas = clasificador.process(alert, out_perf)
            response_payload["perfilamiento"] = out_perf.to_dict()
            response_payload["clasificador"] = out_clas.to_dict()

        elif mode == "analista":
            # Si sólo se ejecuta Analista, simular o recibir clasificación previa
            prev_clas = event.get("clasificador", None)
            out_perf = perfilador.process(alert)
            if not prev_clas:
                out_clas = clasificador.process(alert, out_perf)
            else:
                out_clas = ClasificadorOutput(**prev_clas)

            out_ana = analista.process(alert, out_clas, out_perf)
            response_payload["perfilamiento"] = out_perf.to_dict()
            response_payload["clasificador"] = out_clas.to_dict()
            response_payload["analista"] = out_ana.to_dict()

        elif mode == "ejecutor":
            prev_ana = event.get("analista", None)
            if not prev_ana:
                out_clas = clasificador.process(alert)
                out_ana = analista.process(alert, out_clas)
            else:
                out_ana = AnalistaOutput(**prev_ana)

            out_eje = ejecutor.process(alert, out_ana)
            response_payload["ejecutor"] = out_eje.to_dict()

        else:  # "pipeline" por defecto
            # Pipeline E2E Completo: Perfilador -> [Reglas Duras | Clasificador -> Analista -> Ejecutor] -> Documentador
            t0 = time.time()
            out_perf = perfilador.process(alert)
            t_perf = time.time() - t0

            # Filtros previos determinísticos (Wealth/VIP, hurto, malware/RAT): si
            # alguno dispara, el caso es inequívoco y no tiene sentido pagarle 3
            # llamadas a Bedrock ni arriesgar que el LLM lo interprete distinto en
            # cada corrida -- se construyen Clasificador/Analista/Ejecutor directo
            # a partir del veredicto (0 tokens, 0 costo, 0s). Documentador sigue
            # corriendo igual, para dejar el cierre narrado.
            regla_dura = evaluar_reglas_duras(alert)
            _tokens_cero = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llamadas": 0}

            if regla_dura is not None:
                t_clas = t_ana = t_eje = 0.0
                acciones = regla_dura["acciones_sugeridas"]
                taxonomia_ref = regla_dura["taxonomia_referencial"] or "[NF___ANLISIS]"

                out_clas = ClasificadorOutput(
                    marcacion_aric=regla_dura["marcacion_aric"],
                    cot_justificacion=regla_dura["cot_justificacion"],
                    regla_cold_start_aplicada=alert.is_cold_start(),
                    metadata={"customerid": alert.customerid, "regla_dura": regla_dura["regla"], "tokens": dict(_tokens_cero)},
                )
                out_ana = AnalistaOutput(
                    confirmado=True,
                    clasificacion_final=taxonomia_ref,
                    hipotesis_refutadora="No aplica -- veredicto por regla dura determinística, no por verificación adversarial LLM.",
                    evidencia=[regla_dura["cot_justificacion"]],
                    nivel_incertidumbre="ALTO" if regla_dura["marcacion_aric"] == "RISK_SUSPECTED" else "BAJO",
                    requiere_escalamiento=regla_dura["marcacion_aric"] == "RISK_SUSPECTED",
                    razon_escalamiento=regla_dura["cot_justificacion"] if regla_dura["marcacion_aric"] == "RISK_SUSPECTED" else None,
                    marcacion_aric=regla_dura["marcacion_aric"],
                    modus_operandi=regla_dura["modus_operandi"],
                    metadata={"customerid": alert.customerid, "regla_dura": regla_dura["regla"], "tokens": dict(_tokens_cero)},
                )
                out_eje = EjecutorOutput(
                    marcacion_aric=regla_dura["marcacion_aric"],
                    disparar_voicebot=regla_dura["disparar_voicebot"],
                    accion_operativa="; ".join(acciones) if acciones else "Derivar a revisión manual, sin bloqueo automático.",
                    trazabilidad_id=f"aria-trace-{uuid.uuid4().hex[:12]}",
                    acciones_sugeridas=acciones,
                    observacion_aric=formatear_observacion_aric(
                        taxonomia_ref, alert.channel, habito=None, resumen=regla_dura["cot_justificacion"]
                    ),
                    metadata={"customerid": alert.customerid, "regla_dura": regla_dura["regla"], "tokens": dict(_tokens_cero)},
                )
            else:
                t0 = time.time()
                out_clas = clasificador.process(alert, out_perf)
                t_clas = time.time() - t0

                t0 = time.time()
                out_ana = analista.process(alert, out_clas, out_perf)
                t_ana = time.time() - t0

                t0 = time.time()
                out_eje = ejecutor.process(alert, out_ana)
                t_eje = time.time() - t0

            t0 = time.time()
            out_doc = documentador.process(alert, out_clas, out_ana, out_eje)
            t_doc = time.time() - t0

            response_payload.update({
                "perfilamiento": out_perf.to_dict(),
                "clasificador": out_clas.to_dict(),
                "analista": out_ana.to_dict(),
                "ejecutor": out_eje.to_dict(),
                "documentador": out_doc.to_dict(),
                "regla_dura_aplicada": regla_dura["regla"] if regla_dura else None,
                "performance_seconds": {
                    "perfilador": round(t_perf, 3),
                    "clasificador": round(t_clas, 3),
                    "analista": round(t_ana, 3),
                    "ejecutor": round(t_eje, 3),
                    "documentador": round(t_doc, 3),
                    "total": round(time.time() - start_time, 3)
                }
            })

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(response_payload, ensure_ascii=False, indent=2)
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": "Error interno durante la ejecución del pipeline ARIA",
                "details": str(e)
            }, ensure_ascii=False)
        }


# Permite probar directamente corriendo el script python
if __name__ == "__main__":
    sample_event = {
        "mode": "pipeline",
        "alert": {
            "customerid": "7044052",
            "marcacion_final": "no-risk",
            "razon_marcacion": "[Auto-Close Bulk Purge 72h]",
            "eventtype": "paymentRT",
            "channel": "OM",
            "integrationpoint": "SMGG20211063 - patchPaymentRequest",
            "biocatch_score": 717.0,
            "Model_score": 98427.0,
            "amount_value": 33180000.0,
            "fecha_transaccion": "2026-07-10 09:17:16.000",
            "biocatch_isMobileRat": 0,
            "biocatch_isEmulator": 0,
            "biocatch_isRat": 0,
            "biocatch_isBot": 0,
            "MontoMasAltoGlomo": 42000000.0,
            "MontoMasAltoBreB": 10000000.0
        }
    }
    res = lambda_handler(sample_event)
    print("LAMBDA EXECUTION TEST RESULT:")
    print(res["body"])
