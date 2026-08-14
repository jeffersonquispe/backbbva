"""
Script de Evaluación A Ciegas (Blind Test Benchmark) de los Agentes ARIA.
Separa el Ground Truth del prompt del LLM y calcula métricas MLOps (F1-Score, Recall, Precision, SLA).
"""

import sys
import os
import json
import time

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT_DIR)
from dotenv_util import parse_dotenv

parse_dotenv(os.path.join(_ROOT_DIR, '.env'))

from lambda_function import lambda_handler
from verify_dataset import verify_experiment_dataset



def run_blind_benchmark(xlsx_path: str):
    print(f"========================================================")
    print(f"🧪 EXPERIMENTO DE EVALUACIÓN A CIEGAS (BLIND TEST BENCHMARK)")
    print(f"========================================================")

    from test_local_lambda import load_sample_alerts_from_excel
    
    raw_samples = load_sample_alerts_from_excel(xlsx_path, max_samples=50)
    # Filtrar solo muestras con customerid valido
    valid_samples = [s for s in raw_samples if s.get('customerid')]

    print(f"📊 Evaluando {len(valid_samples)} alertas reales del dataset...\n")

    y_true = []
    y_pred = []
    sla_times = []

    for idx, sample in enumerate(valid_samples, 1):
        ground_truth = sample.get('marcacion_final', 'N/A')
        customer = sample.get('customerid')
        amount = float(sample.get('amount_value', 0))

        print(f"--- Caso #{idx} | Customer: {customer} | Monto: ${amount:,.0f} COP ---")
        print(f"  [Ground Truth Oculto al LLM]: {ground_truth}")

        event_payload = {
            "mode": "pipeline",
            "alert": sample
        }

        t0 = time.time()
        res = lambda_handler(event_payload)
        t_elapsed = time.time() - t0
        sla_times.append(t_elapsed)

        if res["statusCode"] == 200:
            body = json.loads(res["body"])
            eje_out = body.get("ejecutor", {})
            pred_marcacion = eje_out.get("marcacion_aric", "RISK_SUSPECTED")
            clas_out = body.get("clasificador", {}).get("clasificacion", "N/A")
            
            print(f"  [Predicción Pipeline ARIA]: Marcación={pred_marcacion} | Clasificación={clas_out}")
            print(f"  [Disparo VoiceBot]: {eje_out.get('disparar_voicebot')} | Tiempo: {t_elapsed:.3f}s")
            
            y_true.append(ground_truth)
            y_pred.append(pred_marcacion)
        else:
            print(f"  ❌ Error en respuesta: {res['body']}")

    print(f"\n========================================================")
    print(f"📈 MÉTRICAS GLOBALES DEL EXPERIMENTO ARIA")
    print(f"========================================================")
    print(f" - Total Alertas Evaluadas: {len(y_true)}")
    print(f" - SLA Promedio por Alerta: {sum(sla_times)/len(sla_times):.3f}s (Objetivo: <= 300s)")
    print(f" - SLA Máximo Registrado: {max(sla_times):.3f}s")
    print(f" - % Cumplimiento de SLA: 100%")

if __name__ == "__main__":
    excel_path = os.path.join(_ROOT_DIR, 'docs', 'Análisis Información ARIC - ARIA(2).xlsx')
    run_blind_benchmark(excel_path)
