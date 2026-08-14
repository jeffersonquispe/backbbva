"""
Script de Pruebas Locales para la Función AWS Lambda de Agentes ARIA.
Lee registros reales de la hoja 'Muestra' del Excel de ARIC/ARIA y valida la ejecución E2E.
"""

import os
import sys
import json
import zipfile
import xml.etree.ElementTree as ET

sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Importar el handler de la Lambda
from lambda_function import lambda_handler


def load_sample_alerts_from_excel(xlsx_path: str, max_samples: int = 3):
    """Extrae alertas de prueba de la hoja 'Muestra' del archivo Excel."""
    with zipfile.ZipFile(xlsx_path, 'r') as z:
        shared_strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            tree = ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in tree.findall('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si'):
                text_parts = [t.text for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t') if t.text]
                shared_strings.append(''.join(text_parts))

        wb_rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rel_map = {rel.attrib['Id']: rel.attrib['Target'] for rel in wb_rels.findall('{http://schemas.openxmlformats.org/package/2006/relationships}Relationship')}

        wb_tree = ET.fromstring(z.read('xl/workbook.xml'))
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        r_ns = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

        sample_sheet_file = None
        for sheet in wb_tree.find(f'{ns}sheets').findall(f'{ns}sheet'):
            if sheet.attrib['name'] == 'Muestra':
                rid = sheet.attrib[f'{r_ns}id']
                target = rel_map[rid]
                sample_sheet_file = target if target.startswith('xl/') else 'xl/' + target
                break

        if not sample_sheet_file:
            print("⚠️ No se encontró la hoja 'Muestra'")
            return []

        sheet_tree = ET.fromstring(z.read(sample_sheet_file))
        sheet_data = sheet_tree.find(f'{ns}sheetData')
        rows = sheet_data.findall(f'{ns}row')

        # Obtener encabezados
        headers = []
        for c in rows[0].findall(f'{ns}c'):
            t = c.attrib.get('t', '')
            val_elem = c.find(f'{ns}v')
            val = val_elem.text if val_elem is not None else ''
            if t == 's' and val.isdigit():
                idx = int(val)
                if idx < len(shared_strings):
                    val = shared_strings[idx]
            headers.append(val)

        # Parsear filas de datos
        samples = []
        for row in rows[1:max_samples+1]:
            row_dict = {}
            for c in row.findall(f'{ns}c'):
                cell_ref = c.attrib.get('r')
                col_letters = ''.join([ch for ch in cell_ref if ch.isalpha()])
                # Convertir A, B, ... a indice
                col_idx = 0
                for ch in col_letters:
                    col_idx = col_idx * 26 + (ord(ch) - ord('A') + 1)
                col_idx -= 1
                
                if col_idx < len(headers):
                    header_name = headers[col_idx]
                    t = c.attrib.get('t', '')
                    val_elem = c.find(f'{ns}v')
                    val = val_elem.text if val_elem is not None else ''
                    if t == 's' and val.isdigit():
                        idx = int(val)
                        if idx < len(shared_strings):
                            val = shared_strings[idx]
                    elif t == 'inlineStr':
                        is_elem = c.find(f'{ns}is')
                        if is_elem is not None:
                            t_elem = is_elem.find(f'{ns}t')
                            val = t_elem.text if t_elem is not None else ''
                    row_dict[header_name] = val
            samples.append(row_dict)
            
        return samples


def main():
    excel_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'docs', 'Análisis Información ARIC - ARIA(2).xlsx')
    print(f"=== PRUEBA LOCAL DE LAMBDA HANDLER Y AGENTES ARIA ===")
    print(f"Cargando casos de prueba desde Excel: {excel_path}\n")

    test_alerts = load_sample_alerts_from_excel(excel_path, max_samples=3)
    if not test_alerts:
        print("Cargando caso de prueba sintético por fallback...")
        test_alerts = [{
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
        }]

    for idx, sample in enumerate(test_alerts, 1):
        print(f"\n========================================================")
        print(f"🧪 CASO DE PRUEBA #{idx} - Customer: {sample.get('customerid')} | Monto: ${float(sample.get('amount_value', 0)):,.2f} COP")
        print(f"   Servicio: {sample.get('integrationpoint')} | Canal: {sample.get('channel')}")
        print(f"========================================================")

        event_payload = {
            "mode": "pipeline",
            "alert": sample
        }

        response = lambda_handler(event_payload)
        print(f"HTTP StatusCode: {response['statusCode']}")

        if response["statusCode"] == 200:
            res_body = json.loads(response["body"])
            print(f"✅ Pipeline Status: {res_body.get('status')}")
            
            clas = res_body.get("clasificador", {})
            print(f"\n📌 1. CLASIFICADOR:")
            print(f"   Marcación (triage): {clas.get('marcacion_aric')}")
            print(f"   Justificación: {clas.get('cot_justificacion')}")
            print(f"   Cold Start: {clas.get('regla_cold_start_aplicada')}")

            ana = res_body.get("analista", {})
            print(f"\n📌 2. ANALISTA:")
            print(f"   Confirmado: {ana.get('confirmado')} | Final: {ana.get('clasificacion_final')}")
            print(f"   Hipótesis: {ana.get('hipotesis_refutadora')}")
            print(f"   Incertidumbre: {ana.get('nivel_incertidumbre')} | Escalar a Humano: {ana.get('requiere_escalamiento')}")

            eje = res_body.get("ejecutor", {})
            print(f"\n📌 3. EJECUTOR:")
            print(f"   Marcación ARIC: {eje.get('marcacion_aric')}")
            print(f"   Disparar VoiceBot: {eje.get('disparar_voicebot')} (Motivo: {eje.get('motivo_voicebot')})")
            print(f"   Trazabilidad ID: {eje.get('trazabilidad_id')}")

            doc = res_body.get("documentador", {})
            print(f"\n📌 4. DOCUMENTADOR:")
            print(f"   Es Nueva Variante: {doc.get('es_nueva_variante')} | Notificar Senior: {doc.get('notificar_senior')}")
            print(f"   Resumen: {doc.get('resumen_ejecutivo')}")

            perf = res_body.get("performance_seconds", {})
            print(f"\n⏱️ TIEMPOS DE EJECUCIÓN (SLA):")
            print(f"   Clasificador: {perf.get('clasificador')}s | Analista: {perf.get('analista')}s | Ejecutor: {perf.get('ejecutor')}s | Documentador: {perf.get('documentador')}s | TOTAL: {perf.get('total')}s")

        else:
            print(f"❌ Error en respuesta Lambda: {response['body']}")


if __name__ == "__main__":
    main()
