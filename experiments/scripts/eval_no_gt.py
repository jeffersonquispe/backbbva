"""
Evaluación de línea base SIN Ground Truth de los Agentes ARIA (HU-2.5.1, ajustada).

La hoja 'Muestra' del Excel solo tiene 5 registros reales con datos (el resto son
celdas vacías con formato heredado — ver docs/HU-Perfilamiento.md), y el campo
'marcacion_final' que podría servir de referencia mezcla decisiones evaluadas con
cierres automáticos por SLA vencido (ver hallazgos de ambigüedad de 'riskreasons').
Por eso esta evaluación NO calcula precisión/recall contra una etiqueta "verdadera":
mide señales de calidad del proceso que no requieren GT humano:

  - Tasa de confirmación / rectificación del Analista frente al Clasificador
    (acuerdo entre dos agentes, no acuerdo contra una etiqueta).
  - Tasa de escalamiento a analista humano.
  - Distribución de incertidumbre reportada por el Analista.
  - Tasa de fallback (errores técnicos silenciosos) por agente.
  - Precisión de la detección de Cold Start: este es el único punto donde SÍ existe
    una verdad objetiva, porque `AlertInput.is_cold_start()` es una regla
    determinística, no una etiqueta humana.
  - Latencia por etapa frente al SLA de negocio (<5 min por alerta).
  - Distribución histórica de razones reales (hoja "Servicio - razon") como
    referencia poblacional de contraste, no como GT por caso.

Además, se agrega un apartado CON el GT que sí existe en el dataset. El target
es el campo `marcacion_final` de la hoja 'Muestra' (RISK / NO_RISK /
RISK_SUSPECTED) -- la decisión de riesgo real de negocio, no la taxonomía FCP
fina -- excluyendo explícitamente los casos donde `razon_marcacion` indica que
no fue una decisión evaluada (ej. '[Auto-Close Bulk Purge 72h]'). Para comparar
contra ese target: `ClasificadorAgent` decide `marcacion_aric` directamente vía
LLM en su triage rápido (Literal de 3 valores forzado por schema, ver
agents/clasificador.py); `AnalistaAgent` la deriva DETERMINÍSTICAMENTE (no vía
LLM: ver `agents/_marcacion.py`) a partir de señales que sí calcula vía LLM
(incertidumbre, escalamiento, la taxonomía FCP que asigna) -- justamente porque
la evaluación sin GT mostró que pedirle a un LLM de texto libre que respete un
set cerrado tiene alto riesgo de invalidez si no se fuerza por schema. Con n=5
(o menos tras excluir casos no confiables) estas métricas son ilustrativas, no
una línea base estadística: ver 'metrics_con_gt' en el JSON de salida.

Pipeline evaluado: Perfilador -> Clasificador -> Analista.
Ejecutor y Documentador quedan fuera de alcance (ver docs/HU-Perfilamiento.md).
"""

import os
import sys
import json
import time
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT_DIR)
from dotenv_util import parse_dotenv

parse_dotenv(os.path.join(_ROOT_DIR, '.env'))

from schemas import AlertInput
from agents import PerfiladorAgent, ClasificadorAgent, AnalistaAgent
from agents.clasificador import ClasificadorAgent as _ClasificadorAgentCls
from test_local_lambda import load_sample_alerts_from_excel

_TAXONOMIAS_NORMALIZADAS = {
    t.strip('[]').upper() for t in _ClasificadorAgentCls.TAXONOMIAS_PERMITIDAS
}


def _es_taxonomia_valida(valor: str) -> bool:
    """Verifica si un valor de clasificación pertenece al conjunto cerrado FCP,
    tolerando diferencias de corchetes/mayúsculas (ver hallazgo: el Analista no
    valida su 'clasificacion_final' contra la lista cerrada como sí lo hace el
    Clasificador)."""
    return str(valor).strip('[]').upper() in _TAXONOMIAS_NORMALIZADAS


def _normalizar_taxonomia(valor: str) -> str:
    """Mapea un valor libre a su forma canónica con corchetes si pertenece al
    conjunto cerrado FCP. Si no pertenece (ej. una invención del Analista como
    'FR___ACCOUNT_TAKEOVER'), lo etiqueta como 'FUERA_DE_TAXONOMIA' en vez de
    tratarlo como una clase única — así el error queda visible en la matriz de
    confusión en lugar de inflar el número de clases."""
    v = str(valor).strip('[]').upper()
    for t in _ClasificadorAgentCls.TAXONOMIAS_PERMITIDAS:
        if t.strip('[]').upper() == v:
            return t
    return "FUERA_DE_TAXONOMIA"


_MARCACIONES_VALIDAS = {"RISK", "NO_RISK", "RISK_SUSPECTED"}


def _normalizar_marcacion(valor: str) -> str:
    """Normaliza 'no-risk' / 'risk-suspected' / 'risk' (formato de la hoja
    'Muestra') a RISK | NO_RISK | RISK_SUSPECTED (formato de marcacion_aric)."""
    return str(valor).strip().upper().replace("-", "_")


def compute_classification_metrics(y_true, y_pred):
    """Precision/recall/F1 por clase + macro/weighted + matriz de confusión."""
    from sklearn.metrics import precision_recall_fscore_support, confusion_matrix, accuracy_score

    labels = sorted(set(y_true) | set(y_pred))
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="macro", zero_division=0
    )
    weighted_p, weighted_r, weighted_f1, _ = precision_recall_fscore_support(
        y_true, y_pred, average="weighted", zero_division=0
    )
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    return {
        "labels": labels,
        "per_class": [
            {"clase": l, "precision": round(float(p), 4), "recall": round(float(r), 4),
             "f1": round(float(f), 4), "soporte": int(s)}
            for l, p, r, f, s in zip(labels, precision, recall, f1, support)
        ],
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_avg": {"precision": round(float(macro_p), 4), "recall": round(float(macro_r), 4), "f1": round(float(macro_f1), 4)},
        "weighted_avg": {"precision": round(float(weighted_p), 4), "recall": round(float(weighted_r), 4), "f1": round(float(weighted_f1), 4)},
        "confusion_matrix": cm.tolist(),
    }


EXCEL_PATH = os.path.join(_ROOT_DIR, 'docs', 'Análisis Información ARIC - ARIA(2).xlsx')
RESULTS_PATH = os.path.join(_ROOT_DIR, 'output', 'eval_results.json')

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
R_NS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _find_sheet_xml(z, wb_tree, rel_map, sheet_name):
    for sheet in wb_tree.find(f'{NS}sheets').findall(f'{NS}sheet'):
        if sheet.attrib['name'] == sheet_name:
            rid = sheet.attrib[f'{R_NS}id']
            target = rel_map[rid]
            return target if target.startswith('xl/') else 'xl/' + target
    return None


def load_reference_riskreasons_distribution(xlsx_path: str, exclude_unreviewed: bool = True):
    """Distribución histórica real de 'riskreasons_last' desde la hoja 'Servicio - razon'.

    Se usa SOLO como referencia poblacional de contraste (no como GT por caso).
    Por defecto excluye '[Auto-Close Bulk Purge 72h]', que no es una decisión
    evaluada sino un cierre automático por SLA vencido (ver hallazgos de
    ambigüedad de datos discutidos previamente sobre esta hoja).
    """
    with zipfile.ZipFile(xlsx_path, 'r') as z:
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in tree.findall(f'{NS}si'):
                parts = [t.text for t in si.iter(f'{NS}t') if t.text]
                shared_strings.append(''.join(parts))

        wb_rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rel_map = {rel.attrib['Id']: rel.attrib['Target']
                   for rel in wb_rels.findall('{http://schemas.openxmlformats.org/package/2006/relationships}Relationship')}
        wb_tree = ET.fromstring(z.read('xl/workbook.xml'))

        sheet_file = _find_sheet_xml(z, wb_tree, rel_map, 'Servicio - razon')
        if not sheet_file:
            return {}

        sheet_tree = ET.fromstring(z.read(sheet_file))
        rows = sheet_tree.find(f'{NS}sheetData').findall(f'{NS}row')

        def cell_value(c):
            t = c.attrib.get('t', '')
            v = c.find(f'{NS}v')
            val = v.text if v is not None else ''
            if t == 's' and val.isdigit():
                idx = int(val)
                if idx < len(shared_strings):
                    val = shared_strings[idx]
            return val

        headers = [cell_value(c) for c in rows[0].findall(f'{NS}c')]
        try:
            razon_idx = headers.index('riskreasons_last')
            trx_idx = headers.index('Transacciones')
        except ValueError:
            return {}

        totals = Counter()
        for row in rows[1:]:
            cells = row.findall(f'{NS}c')
            if len(cells) <= max(razon_idx, trx_idx):
                continue
            values = {}
            for c in cells:
                ref = c.attrib.get('r', '')
                col_letters = ''.join(ch for ch in ref if ch.isalpha())
                col_idx = 0
                for ch in col_letters:
                    col_idx = col_idx * 26 + (ord(ch) - ord('A') + 1)
                col_idx -= 1
                if col_idx < len(headers):
                    values[headers[col_idx]] = cell_value(c)

            razon = values.get('riskreasons_last', '')
            if not razon:
                continue
            if exclude_unreviewed and razon == '[Auto-Close Bulk Purge 72h]':
                continue
            try:
                trx = float(str(values.get('Transacciones', '0')).replace(',', '.'))
            except ValueError:
                trx = 0.0
            totals[razon] += trx

        total_sum = sum(totals.values())
        if total_sum == 0:
            return {}
        return {k: round(v / total_sum, 4) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])}


def run_no_gt_evaluation(xlsx_path: str = EXCEL_PATH, max_samples: int = 50):
    print("========================================================")
    print("🧪 EVALUACIÓN DE LÍNEA BASE SIN GROUND TRUTH — ARIA")
    print("   Pipeline: Perfilador -> Clasificador -> Analista")
    print("========================================================")

    raw_samples = load_sample_alerts_from_excel(xlsx_path, max_samples=max_samples)
    valid_samples = [s for s in raw_samples if s.get('customerid')]
    print(f"📊 Casos reales disponibles en hoja 'Muestra': {len(valid_samples)}")
    if len(valid_samples) < 10:
        print("⚠️  Muestra reducida: esto es un piloto/smoke-test, no una línea base "
              "estadísticamente significativa (ver docs/HU-Perfilamiento.md, HU-2.5.1).")

    perfilador = PerfiladorAgent()
    clasificador = ClasificadorAgent()
    analista = AnalistaAgent()

    cases = []
    for idx, sample in enumerate(valid_samples, 1):
        customer = sample.get('customerid')
        print(f"\n--- Caso #{idx} | Customer: {customer} ---")
        alert = AlertInput.from_dict(sample)

        t0 = time.time()
        out_perf = perfilador.process(alert)
        t_perf = time.time() - t0

        t0 = time.time()
        out_clas = clasificador.process(alert, out_perf)
        t_clas = time.time() - t0

        t0 = time.time()
        out_ana = analista.process(alert, out_clas, out_perf)
        t_ana = time.time() - t0

        cold_start_real = alert.is_cold_start()
        cold_start_llm = out_clas.regla_cold_start_aplicada

        # Ground truth objetivo: el campo `marcacion_final` (RISK / NO_RISK /
        # RISK_SUSPECTED) de la hoja 'Muestra' — es el target real de negocio, no
        # la taxonomía FCP fina. La confiabilidad del caso se sigue decidiendo por
        # `razon_marcacion`: si fue un cierre automático (ej. '[Auto-Close Bulk
        # Purge 72h]') en vez de una decisión evaluada, se excluye igual, porque
        # su `marcacion_final` tampoco refleja una evaluación real.
        gt_razon = alert.razon_marcacion
        gt_confiable = bool(gt_razon) and _es_taxonomia_valida(gt_razon)
        gt_marcacion = alert.marcacion_final

        case_record = {
            "customerid": customer,
            "amount_value": alert.amount_value,
            "integrationpoint": alert.integrationpoint,
            "channel": alert.channel,
            "perfilamiento": out_perf.to_dict(),
            "clasificador": out_clas.to_dict(),
            "analista": out_ana.to_dict(),
            "cold_start_real": cold_start_real,
            "cold_start_llm": cold_start_llm,
            "cold_start_match": cold_start_real == cold_start_llm,
            # El Clasificador ya no propone taxonomía (ver agents/clasificador.py) --
            # decide directamente RISK/NO_RISK/RISK_SUSPECTED en su triage rápido, así
            # que lo que el Analista puede "rectificar" ahora es ese triage, no una
            # taxonomía. La taxonomía FCP la asigna únicamente el Analista.
            "triage_cambio": out_clas.marcacion_aric != out_ana.marcacion_aric,
            "analista_taxonomia_valida": _es_taxonomia_valida(out_ana.clasificacion_final),
            "fallback_perfilador": "error" in out_perf.metadata,
            "fallback_clasificador": "error" in out_clas.metadata,
            "fallback_analista": "error" in out_ana.metadata,
            "tiempos": {"perfilador": round(t_perf, 3), "clasificador": round(t_clas, 3),
                        "analista": round(t_ana, 3), "total": round(t_perf + t_clas + t_ana, 3)},
            "ground_truth_razon_marcacion": gt_razon,
            "ground_truth_confiable": gt_confiable,
            "ground_truth_marcacion_final": gt_marcacion,
            "ground_truth_marcacion_normalizada": _normalizar_marcacion(gt_marcacion) if gt_confiable else None,
            "clasificador_marcacion_aric": out_clas.marcacion_aric,
            "analista_marcacion_aric": out_ana.marcacion_aric,
            # Se conservan por trazabilidad, aunque el target ahora es la marcación de riesgo:
            "ground_truth_normalizado": _normalizar_taxonomia(gt_razon) if gt_confiable else None,
            "analista_normalizado": _normalizar_taxonomia(out_ana.clasificacion_final),
        }
        cases.append(case_record)

        print(f"  Perfilamiento: {t_perf:.2f}s | Clasificador: {out_clas.marcacion_aric} ({t_clas:.2f}s)")
        print(f"  Analista: confirmado={out_ana.confirmado} | final={out_ana.clasificacion_final} "
              f"| incertidumbre={out_ana.nivel_incertidumbre} | escala={out_ana.requiere_escalamiento} "
              f"({t_ana:.2f}s)")
        print(f"  Cold Start -> real={cold_start_real} | LLM={cold_start_llm} "
              f"| match={case_record['cold_start_match']}")
        print(f"  Marcación ARIC -> Analista={out_ana.marcacion_aric} | "
              f"Clasificador (triage)={case_record['clasificador_marcacion_aric']} | "
              f"GT={gt_marcacion!r} (confiable={gt_confiable})")

    # --- Agregados sin GT ---
    n = len(cases)
    summary = {}
    if n > 0:
        confirmados = sum(1 for c in cases if c["analista"]["confirmado"])
        escalados = sum(1 for c in cases if c["analista"]["requiere_escalamiento"])
        cold_start_matches = sum(1 for c in cases if c["cold_start_match"])
        fallback_any = sum(1 for c in cases if c["fallback_perfilador"] or c["fallback_clasificador"] or c["fallback_analista"])
        taxonomia_invalida = sum(1 for c in cases if not c["analista_taxonomia_valida"])
        triage_cambio = sum(1 for c in cases if c["triage_cambio"])

        summary = {
            "total_casos": n,
            "tasa_confirmacion_analista": round(confirmados / n, 4),
            "tasa_rectificacion_analista": round(1 - confirmados / n, 4),
            "tasa_rectificacion_triage": round(triage_cambio / n, 4),
            "tasa_analista_taxonomia_invalida": round(taxonomia_invalida / n, 4),
            "tasa_escalamiento": round(escalados / n, 4),
            "tasa_cold_start_correcto": round(cold_start_matches / n, 4),
            "tasa_fallback": round(fallback_any / n, 4),
            "distribucion_incertidumbre": dict(Counter(c["analista"]["nivel_incertidumbre"] for c in cases)),
            "distribucion_triage_inicial": dict(Counter(c["clasificador"]["marcacion_aric"] for c in cases)),
            "distribucion_clasificacion_final": dict(Counter(c["analista"]["clasificacion_final"] for c in cases)),
            "latencia_promedio_seg": {
                "perfilador": round(sum(c["tiempos"]["perfilador"] for c in cases) / n, 3),
                "clasificador": round(sum(c["tiempos"]["clasificador"] for c in cases) / n, 3),
                "analista": round(sum(c["tiempos"]["analista"] for c in cases) / n, 3),
                "total": round(sum(c["tiempos"]["total"] for c in cases) / n, 3),
            },
            "latencia_maxima_seg": round(max(c["tiempos"]["total"] for c in cases), 3),
            "sla_objetivo_seg": 300,
            "sla_cumplido_pct": round(sum(1 for c in cases if c["tiempos"]["total"] <= 300) / n, 4),
        }

    print("\n========================================================")
    print("📈 RESUMEN — MÉTRICAS SIN GROUND TRUTH")
    print("========================================================")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    print("\n📚 Cargando distribución histórica de referencia (hoja 'Servicio - razon')...")
    reference_dist = load_reference_riskreasons_distribution(xlsx_path)

    # --- Métricas clásicas CON GT, target = marcación de riesgo (RISK / NO_RISK / RISK_SUSPECTED) ---
    print("\n========================================================")
    print("📐 MÉTRICAS CLÁSICAS DE CLASIFICACIÓN — TARGET: marcación de riesgo")
    print("========================================================")
    gt_cases = [c for c in cases if c["ground_truth_confiable"]]
    excluidos = [c for c in cases if not c["ground_truth_confiable"]]
    print(f"  Casos con GT confiable: {len(gt_cases)}/{n} "
          f"(excluidos: {[c['customerid'] for c in excluidos]} — "
          f"razon_marcacion no evaluada, ej. cierre automático)")

    metrics_con_gt = {
        "target": "marcacion_final (RISK | NO_RISK | RISK_SUSPECTED)",
        "advertencia": (
            f"n={len(gt_cases)} casos con GT confiable (de {n} totales). Con una muestra "
            "tan pequeña estos números son ilustrativos, NO una línea base estadísticamente "
            "significativa. GT = campo 'marcacion_final' de la hoja 'Muestra', excluyendo "
            "casos donde 'razon_marcacion' indica que no fue una decisión evaluada "
            "(ej. '[Auto-Close Bulk Purge 72h]')."
        ),
        "n_total_casos": n,
        "n_casos_con_gt_confiable": len(gt_cases),
        "casos_excluidos": [
            {"customerid": c["customerid"], "razon_marcacion_original": c["ground_truth_razon_marcacion"]}
            for c in excluidos
        ],
        "clasificador_vs_gt": None,
        "analista_vs_gt": None,
    }

    if gt_cases:
        y_true = [c["ground_truth_marcacion_normalizada"] for c in gt_cases]
        y_pred_clas = [c["clasificador_marcacion_aric"] for c in gt_cases]
        y_pred_ana = [c["analista_marcacion_aric"] for c in gt_cases]

        metrics_con_gt["clasificador_vs_gt"] = compute_classification_metrics(y_true, y_pred_clas)
        metrics_con_gt["analista_vs_gt"] = compute_classification_metrics(y_true, y_pred_ana)

        print(f"  Clasificador (triage directo, sin paso adversarial) -> accuracy: "
              f"{metrics_con_gt['clasificador_vs_gt']['accuracy']:.2f} "
              f"| F1 macro: {metrics_con_gt['clasificador_vs_gt']['macro_avg']['f1']:.2f}")
        print(f"  Analista (marcacion_aric, con adversarial)           -> accuracy: "
              f"{metrics_con_gt['analista_vs_gt']['accuracy']:.2f} "
              f"| F1 macro: {metrics_con_gt['analista_vs_gt']['macro_avg']['f1']:.2f}")
    else:
        print("  ⚠️ Ningún caso tiene GT confiable — no se pueden calcular métricas.")

    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "scope": "Perfilador -> Clasificador -> Analista (Ejecutor y Documentador fuera de alcance)",
        "note": "Evaluación sin Ground Truth humano, más un apartado con GT limitado. Ver docstring de eval_no_gt.py para el detalle metodológico.",
        "summary": summary,
        "cases": cases,
        "reference_distribution_riskreasons": reference_dist,
        "metrics_con_gt": metrics_con_gt,
    }

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Resultados guardados en: {RESULTS_PATH}")
    print("   Visualízalos con: streamlit run app/streamlit_dashboard.py")

    return output


if __name__ == "__main__":
    run_no_gt_evaluation()
