"""
Piloto de evaluación a ciegas del pipeline ARIA completo (Perfilador -> Clasificador
-> Analista -> Ejecutor -> Documentador) contra una muestra estratificada de
Muestra_200_ARIA_alerts_por_gt.json.

Cada alert ya viene sin marcacion_final; aquí también se retiran tipo y eventid
antes de invocar el pipeline (alias directo del GT — ver app/app.py
GT_LEAK_FIELDS). razon_marcacion SÍ se deja en el payload: Clasificador y
Analista pueden usarla como contexto, no es un campo a clasificar en sí mismo.

Los casos se procesan en paralelo con un ThreadPoolExecutor: cada caso hace 5
llamadas secuenciales a Bedrock (una por agente) que no se pueden paralelizar
entre sí por sus dependencias de datos, pero los casos entre sí son
independientes. Los agentes ya están instanciados a nivel de módulo en
lambda_function.py y se reutilizan entre invocaciones; ChatBedrock/boto3 no
mantienen estado mutable entre llamadas, así que son seguros de compartir
entre threads.

Cada corrida es un "experimento" con su propio run_id, guardado en
output/pilots/<run_id>/:
  - config.json:      parámetros de la corrida (total, workers, dataset).
  - checkpoint.jsonl:  un caso resuelto por línea, escrito y flusheado al
                        instante -> si el proceso se cae o se corta, se puede
                        retomar sin perder los casos ya pagados/computados.
  - summary.json:      métricas agregadas (accuracy, matriz de confusión,
                        tokens, fallbacks), regeneradas después de cada caso
                        -> el dashboard puede leer el progreso de una corrida
                        que todavía está en marcha, no solo la terminada.
output/pilots/registry.jsonl registra cada experimento (inicio/fin) para que
el dashboard pueda listar corridas pasadas.
output/pilot_alerts_por_gt_results.json siempre espeja el summary.json del
experimento más reciente, para no romper el path que ya lee el dashboard.

Uso:
    python scripts/run_pilot_alerts_por_gt.py [--total 100] [--workers 3]
    python scripts/run_pilot_alerts_por_gt.py --resume pilot_20260813_150000   # retomar
"""
import argparse
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT_DIR)

from dotenv_util import parse_dotenv

parse_dotenv(os.path.join(_ROOT_DIR, '.env'))

from lambda_function import lambda_handler
from pricing import calcular_costos_por_agente

ALERTS_JSON = os.path.join(_ROOT_DIR, 'Muestra_200_ARIA_alerts_por_gt.json')
PILOTS_DIR = os.path.join(_ROOT_DIR, 'output', 'pilots')
REGISTRY_PATH = os.path.join(PILOTS_DIR, 'registry.jsonl')
LEGACY_MIRROR_PATH = os.path.join(_ROOT_DIR, 'output', 'pilot_alerts_por_gt_results.json')
# razon_marcacion ya NO se retira antes de invocar el pipeline (ver AlertInput /
# clasificador.py / analista.py): el Clasificador y el Analista ahora pueden
# leerla como contexto adicional, sin que sea obligatorio basarse en ella para
# clasificar. eventid/marcacion_final/tipo siguen fuera del payload del
# pipeline porque son metadata de dataset o alias directo del GT.
GT_LEAK_FIELDS = ("eventid", "marcacion_final", "tipo")
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
GRUPOS_GT = ("risk", "no-risk", "risk-suspected")
LABELS = ["RISK", "NO_RISK", "RISK_SUSPECTED"]
AGENTES = ("perfilamiento", "clasificador", "analista", "ejecutor", "documentador")
# Agentes que se comparan contra el GT (RISK/NO_RISK/RISK_SUSPECTED). Clasificador
# decide su marcacion_aric directamente (LLM, Literal de 3 valores -- ver
# agents/clasificador.py); Analista la deriva determinísticamente de su taxonomía FCP
# + nivel_incertidumbre (ver agents/_marcacion.py); Ejecutor decide la oficial vía su
# propio LLM. Acá solo se lee lo que cada agente ya devolvió -- no se deriva nada
# en este script.
AGENTES_EVALUADOS = ("clasificador", "analista", "ejecutor")


_print_lock = threading.Lock()
_checkpoint_lock = threading.Lock()


def normalizar_gt(grupo: str) -> str:
    return grupo.strip().upper().replace("-", "_")


def construir_piloto(alert_groups: dict, total: int) -> list:
    """Reparte `total` casos lo mas parejo posible entre los 3 grupos GT.
    Determinístico: el mismo `total` siempre arma la misma lista, en el mismo
    orden -> necesario para que retomar por índice sea seguro."""
    base, resto = divmod(total, len(GRUPOS_GT))
    piloto = []
    for i, grupo in enumerate(GRUPOS_GT):
        n = base + (1 if i < resto else 0)
        muestras = alert_groups.get(grupo, [])
        for alert in muestras[:n]:
            piloto.append((grupo, alert))
    return piloto


def registrar_evento(run_id: str, evento: str, **campos):
    os.makedirs(PILOTS_DIR, exist_ok=True)
    linea = {"run_id": run_id, "evento": evento, "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), **campos}
    with open(REGISTRY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def cargar_checkpoint(checkpoint_path: str) -> dict:
    """Casos ya resueltos, indexados por su posición en `construir_piloto`."""
    completados = {}
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                r = json.loads(linea)
                completados[r["idx"]] = r
    return completados


def guardar_caso_checkpoint(checkpoint_path: str, resultado: dict):
    with _checkpoint_lock:
        with open(checkpoint_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(resultado, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())


def procesar_caso(idx: int, total: int, grupo: str, alert_raw: dict) -> dict:
    # eventid se guarda para análisis retroactivo pero nunca se manda al pipeline
    # (retirado junto con marcacion_final/tipo vía GT_LEAK_FIELDS). razon_marcacion
    # SÍ viaja dentro de `alert` -> el Clasificador y el Analista pueden leerla como
    # contexto adicional (no es obligatorio basarse en ella para clasificar); se
    # guarda aparte también aquí solo para poder segmentar accuracy por tipo de
    # fraude en el reporte.
    eventid = alert_raw.get("eventid")
    razon_marcacion = alert_raw.get("razon_marcacion")
    alert = {k: v for k, v in alert_raw.items() if k not in GT_LEAK_FIELDS}
    customer = alert.get("customerid")
    gt_esperado = normalizar_gt(grupo)

    with _print_lock:
        print(f"--- Caso {idx + 1}/{total} | Customer {customer} | GT esperado: {gt_esperado} | INICIANDO ---", flush=True)

    t0 = time.time()
    res = lambda_handler({"mode": "pipeline", "alert": alert})
    t_elapsed = time.time() - t0

    if res["statusCode"] != 200:
        resultado = {
            "idx": idx, "customerid": customer, "eventid": eventid, "razon_marcacion": razon_marcacion,
            "gt_esperado": gt_esperado, "error": res["body"], "tiempo_seg": round(t_elapsed, 2),
        }
        with _print_lock:
            print(f"--- Caso {idx + 1}/{total} | Customer {customer} | ERROR HTTP {res['statusCode']} | {t_elapsed:.1f}s ---", flush=True)
        return resultado

    body = json.loads(res["body"])
    clas = body.get("clasificador", {})
    ana = body.get("analista", {})
    eje = body.get("ejecutor", {})

    pred_clasificador = clas.get("marcacion_aric", "N/A")
    pred_analista = ana.get("marcacion_aric", "N/A")
    pred = eje.get("marcacion_aric", "N/A")

    coincide_clasificador = pred_clasificador == gt_esperado
    coincide_analista = pred_analista == gt_esperado
    coincide = pred == gt_esperado

    fallbacks_caso = [a for a in AGENTES if body.get(a, {}).get("metadata", {}).get("error")]
    tokens_por_agente = {
        a: body.get(a, {}).get("metadata", {}).get("tokens", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llamadas": 0})
        for a in AGENTES
    }
    tokens_totales_caso = sum(t.get("total_tokens", 0) for t in tokens_por_agente.values())
    costo_por_agente_caso = calcular_costos_por_agente(tokens_por_agente, MODEL_ID)
    costo_total_caso_usd = costo_por_agente_caso["_total"]

    with _print_lock:
        print(f"--- Caso {idx + 1}/{total} | Customer {customer} | Ejecutor: {pred} "
              f"{'OK' if coincide else 'DIFF'} | Analista: {pred_analista} {'OK' if coincide_analista else 'DIFF'} "
              f"| Clasificador: {pred_clasificador} {'OK' if coincide_clasificador else 'DIFF'} "
              f"| {t_elapsed:.1f}s | {tokens_totales_caso} tokens | ${costo_total_caso_usd:.4f} ---", flush=True)

    return {
        "idx": idx,
        "customerid": customer,
        "eventid": eventid,
        "razon_marcacion": razon_marcacion,
        "gt_esperado": gt_esperado,
        "marcacion_predicha": pred,
        "coincide": coincide,
        "marcacion_predicha_clasificador": pred_clasificador,
        "coincide_clasificador": coincide_clasificador,
        "marcacion_predicha_analista": pred_analista,
        "coincide_analista": coincide_analista,
        "clasificacion_final": body.get("analista", {}).get("clasificacion_final"),
        "nivel_incertidumbre": body.get("analista", {}).get("nivel_incertidumbre"),
        "requiere_escalamiento": body.get("analista", {}).get("requiere_escalamiento"),
        "tiempo_seg": round(t_elapsed, 2),
        "performance_seconds": body.get("performance_seconds", {}),
        "fallbacks_caso": fallbacks_caso,
        "tokens_por_agente": tokens_por_agente,
        "tokens_totales_caso": tokens_totales_caso,
        "costo_por_agente_caso_usd": costo_por_agente_caso,
        "costo_total_caso_usd": costo_total_caso_usd,
    }


def _metricas_agente(evaluados_r: list, campo_pred: str, campo_coincide: str) -> dict:
    """Accuracy + matriz de confusión de un agente contra el GT de 3 clases, a partir
    del campo de predicción/acierto que le corresponde en cada caso (ver AGENTES_EVALUADOS)."""
    aciertos = sum(1 for r in evaluados_r if r.get(campo_coincide))
    matriz = Counter((r["gt_esperado"], r.get(campo_pred)) for r in evaluados_r)
    return {
        "evaluados": len(evaluados_r),
        "aciertos": aciertos,
        "accuracy": aciertos / len(evaluados_r) if evaluados_r else None,
        "confusion_matrix": {
            "labels": LABELS,
            "matrix": [[matriz.get((real, pred), 0) for pred in LABELS] for real in LABELS],
        },
    }


def construir_resumen(run_id: str, params: dict, resultados: list, total: int, estado: str) -> dict:
    evaluados_r = [r for r in resultados if "coincide" in r]

    # Métricas por separado para Clasificador, Analista y Ejecutor: cada uno se
    # compara contra el mismo GT de 3 clases (RISK/NO_RISK/RISK_SUSPECTED), pero el
    # Clasificador llega ahí vía la taxonomía FCP derivada (ver
    # derivar_marcacion_clasificador) porque esa taxonomía, no la marcación de
    # riesgo, es lo que ese agente decide de verdad.
    metricas_por_agente = {
        "clasificador": _metricas_agente(evaluados_r, "marcacion_predicha_clasificador", "coincide_clasificador"),
        "analista": _metricas_agente(evaluados_r, "marcacion_predicha_analista", "coincide_analista"),
        "ejecutor": _metricas_agente(evaluados_r, "marcacion_predicha", "coincide"),
    }

    fallback_por_agente = Counter()
    for r in evaluados_r:
        for a in r.get("fallbacks_caso", []):
            fallback_por_agente[a] += 1

    tokens_por_agente = {a: {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llamadas": 0} for a in AGENTES}
    for r in evaluados_r:
        for a, t in r.get("tokens_por_agente", {}).items():
            for k in tokens_por_agente[a]:
                tokens_por_agente[a][k] += t.get(k, 0)
    tokens_totales = sum(t["total_tokens"] for t in tokens_por_agente.values())
    model_id = params.get("model_id", MODEL_ID)
    costo_por_agente_usd = calcular_costos_por_agente(tokens_por_agente, model_id)
    costo_total_usd = costo_por_agente_usd.pop("_total")

    tiempos = [r["tiempo_seg"] for r in resultados if "tiempo_seg" in r]
    # aciertos/accuracy/confusion_matrix a nivel raíz quedan igual que antes (la
    # marcación oficial del pipeline, la del Ejecutor) para no romper a quien ya lee
    # esas claves (app/app.py) -- el desglose nuevo por agente vive en
    # "metricas_por_agente".
    metricas_ejecutor = metricas_por_agente["ejecutor"]

    return {
        "run_id": run_id,
        "estado": estado,  # "en_progreso" | "completado" | "interrumpido"
        "params": params,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_casos": total,
        "casos_procesados": len(resultados),
        "evaluados": len(evaluados_r),
        "aciertos": metricas_ejecutor["aciertos"],
        "accuracy": metricas_ejecutor["accuracy"],
        "tiempo_promedio_seg": sum(tiempos) / len(tiempos) if tiempos else None,
        "tiempo_maximo_seg": max(tiempos) if tiempos else None,
        "fallback_por_agente": dict(fallback_por_agente),
        "model_id": model_id,
        "tokens_totales": tokens_totales,
        "tokens_por_agente": tokens_por_agente,
        "costo_total_usd": costo_total_usd,
        "costo_por_agente_usd": costo_por_agente_usd,
        "confusion_matrix": metricas_ejecutor["confusion_matrix"],
        "metricas_por_agente": metricas_por_agente,
        "casos": sorted(resultados, key=lambda r: r["idx"]),
    }


def guardar_resumen(run_dir: str, resumen: dict):
    summary_path = os.path.join(run_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    # Espejo en la ruta vieja para que el dashboard actual siga funcionando
    # sin cambios, y para que muestre progreso en vivo de la corrida activa.
    with open(LEGACY_MIRROR_PATH, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=20)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--resume", type=str, default=None, metavar="RUN_ID",
                         help="Retoma un experimento existente por su run_id (carpeta en output/pilots/).")
    args = parser.parse_args()

    with open(ALERTS_JSON, "r", encoding="utf-8") as f:
        alert_groups = json.load(f)

    piloto = construir_piloto(alert_groups, args.total)
    total = len(piloto)

    if args.resume:
        run_id = args.resume
        run_dir = os.path.join(PILOTS_DIR, run_id)
        if not os.path.isdir(run_dir):
            print(f"ERROR: no existe output/pilots/{run_id}/ — no se puede retomar.")
            sys.exit(1)
    else:
        run_id = f"pilot_{time.strftime('%Y%m%d_%H%M%S')}_w{args.workers}"
        run_dir = os.path.join(PILOTS_DIR, run_id)
        os.makedirs(run_dir, exist_ok=True)

    checkpoint_path = os.path.join(run_dir, "checkpoint.jsonl")
    config_path = os.path.join(run_dir, "config.json")
    params = {"total": total, "workers": args.workers, "alerts_json": os.path.basename(ALERTS_JSON), "model_id": MODEL_ID}

    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)

    completados = cargar_checkpoint(checkpoint_path)
    pendientes = [(idx, grupo, alert_raw) for idx, (grupo, alert_raw) in enumerate(piloto) if idx not in completados]

    print(f"========================================================")
    print(f"PILOTO BLIND TEST ARIA — run_id={run_id}")
    print(f"{total} casos totales, {args.workers} en paralelo, "
          f"{len(completados)} ya resueltos (checkpoint), {len(pendientes)} pendientes")
    print(f"========================================================\n")

    registrar_evento(run_id, "reanudado" if completados else "iniciado", **params, pendientes=len(pendientes))

    resultados = list(completados.values())
    t_batch0 = time.time()
    interrumpido = False
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(procesar_caso, idx, total, grupo, alert_raw): idx
                       for idx, grupo, alert_raw in pendientes}
            for fut in as_completed(futures):
                resultado = fut.result()
                guardar_caso_checkpoint(checkpoint_path, resultado)
                resultados.append(resultado)
                resumen_parcial = construir_resumen(run_id, params, resultados, total, "en_progreso")
                guardar_resumen(run_dir, resumen_parcial)
    except KeyboardInterrupt:
        interrumpido = True
        print("\n Interrumpido por el usuario — el checkpoint ya tiene los casos resueltos hasta ahora.")

    t_batch = time.time() - t_batch0
    estado_final = "interrumpido" if interrumpido else "completado"
    resumen = construir_resumen(run_id, params, resultados, total, estado_final)
    resumen["tiempo_total_batch_seg"] = round(t_batch, 2)
    guardar_resumen(run_dir, resumen)
    registrar_evento(run_id, estado_final, casos_procesados=len(resultados), total_casos=total,
                      accuracy=resumen["accuracy"], tokens_totales=resumen["tokens_totales"],
                      costo_total_usd=resumen["costo_total_usd"])

    print(f"\n========================================================")
    print(f"RESUMEN PILOTO — {estado_final.upper()}")
    print(f"========================================================")
    print(f"Casos evaluados: {resumen['evaluados']}/{total}")
    print("\nAccuracy vs GT por agente (RISK / NO_RISK / RISK_SUSPECTED):")
    for a in AGENTES_EVALUADOS:
        m = resumen["metricas_por_agente"][a]
        if m["accuracy"] is not None:
            print(f"  {a:14s} {m['aciertos']}/{m['evaluados']} = {m['accuracy']:.0%}")
        else:
            print(f"  {a:14s} sin casos evaluados")
    print(f"\nTiempo de este batch: {t_batch:.1f}s")
    if resumen["tiempo_promedio_seg"]:
        print(f"Tiempo promedio/caso: {resumen['tiempo_promedio_seg']:.1f}s | máximo: {resumen['tiempo_maximo_seg']:.1f}s")
    if resumen["fallback_por_agente"]:
        print(f"Fallbacks por agente: {resumen['fallback_por_agente']}")
    else:
        print("Fallbacks por agente: ninguno")
    print(f"\nModelo: {resumen['model_id']}")
    print(f"Tokens totales: {resumen['tokens_totales']:,} | Costo total: ${resumen['costo_total_usd']:.4f} USD")
    for a in AGENTES:
        t = resumen["tokens_por_agente"][a]
        c = resumen["costo_por_agente_usd"][a]
        print(f"  {a:14s} input={t['input_tokens']:>7,} output={t['output_tokens']:>7,} "
              f"total={t['total_tokens']:>7,} ({t['llamadas']} llamadas) -> ${c:.4f} USD")
    print("\nMatriz de confusión del Ejecutor -- marcación oficial del pipeline (real -> predicho):")
    cm = resumen["confusion_matrix"]["matrix"]
    for i, real in enumerate(LABELS):
        fila = " | ".join(f"{pred}={cm[i][j]}" for j, pred in enumerate(LABELS))
        print(f"  {real:16s} {fila}")

    print(f"\n-> run_id: {run_id}")
    print(f"-> Checkpoint: {checkpoint_path}")
    print(f"-> Resumen: {os.path.join(run_dir, 'summary.json')}")
    if interrumpido:
        print(f"-> Para retomar: python scripts/run_pilot_alerts_por_gt.py --resume {run_id}")


if __name__ == "__main__":
    main()
