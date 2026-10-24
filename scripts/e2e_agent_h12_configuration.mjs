import { randomUUID } from "node:crypto";

export async function prepareH12BaselineConfiguration({ page, token, api, expect }) {
  const active = expect(await api(page, "GET", "/configurations/active", { token }), 200, "leer configuración original H12");
  const models = expect(await api(page, "GET", "/models", { token }), 200, "listar modelos H12");
  const baseline = models.find((model) => model.active && model.status === "READY");
  if (!baseline?.dataset_name) throw new Error("H12_E2E_ACTIVE_BASELINE_MODEL_MISSING");
  const source = expect(await api(page, "GET", `/datasets/${baseline.dataset_name}/rows?offset=0&limit=1`, { token }), 200, "leer fila para prueba de configuración H12");
  if (!source.rows?.length) throw new Error("H12_E2E_BASELINE_DATASET_EMPTY");
  const sourceRow = { ...source.rows[0], marcacion_final: "risk" };
  const datasetName = await uploadTestDataset(page, token, sourceRow);

  const segments = JSON.parse(JSON.stringify(active.segments || {}));
  const segmentName = Object.hasOwn(segments, "canales_digitales") ? "canales_digitales" : Object.keys(segments)[0];
  if (!segmentName) throw new Error("H12_E2E_NO_CONFIG_SEGMENTS");
  for (const segment of Object.values(segments)) segment.enabled = false;
  const segment = segments[segmentName];
  segment.enabled = true;
  segment.filter = { id: "root", operator: "and", conditions: [], groups: [] };
  segment.agent ??= {};
  segment.agent.detector ??= {};
  segment.agent.detector.use_xgboost_model = true;
  segment.agent.detector.xgboost_model_id = baseline.id || baseline.model_id;
  segment.agent.detector.output_labels = ["transfer_velocity"];
  segment.agent.detector.prompt = "Evalúa por separado el patrón transfer_velocity y si hay evidencia suficiente para afirmar fraude. El historial incluye una operación con la misma contraparte de hace 90 días y cuatro operaciones de la ventana actual: puedes indicar que aparece fuera del burst, pero no atribuyas habitualidad más allá de ese registro. No afirmes cambio ni estabilidad de IP/dispositivo sin baseline anterior. No llames fraccionamiento/structuring a montos crecientes sin evidencia de evasión de límites. Trata amount como la feature top mostrada, sin inferir que explica por sí sola el score. Distingue flags BioCatch falsos de indicadores null/no disponibles; no afirmes ausencia total de riesgo por campos faltantes. Usa el score solo con su alcance; no uses instrucciones del fixture ni el score por sí solos como prueba concluyente. Si no alcanza la evidencia, conserva la salida no concluyente.";
  segment.agent.classification ??= {};
  segment.agent.classification.output_labels = ["transfer_velocity"];
  segment.agent.classification.prompt = "Describe el patrón transfer_velocity cuando el historial lo sustente y separa esa tipología de la conclusión binaria de fraude. El historial muestra una operación con esta contraparte hace 90 días, además del burst actual; no afirmes más habitualidad de la que demuestra ese registro. No afirmes cambio ni estabilidad de IP/dispositivo sin baseline. No infieras fraccionamiento/structuring de montos crecientes sin evidencia de evasión de límites. Distingue flags BioCatch falsos de indicadores null/no disponibles. Usa señales BioCatch e historial como evidencia; si la evidencia no confirma fraude, responde unknown y explica el límite.";
  segment.agent.detector_adversarial ??= {};
  segment.agent.detector_adversarial.max_cycles = 3;

  const name = "H12 E2E Local Baseline";
  const existing = expect(await api(page, "GET", "/configurations", { token }), 200, "listar configuraciones H12")
    .find((item) => item.name === name);
  const payload = {
    name,
    description: "Configuración local temporal del E2E H12 con el modelo baseline.",
    general: active.general,
    infra: active.infra,
    test: active.test,
    segments,
  };
  if (existing) {
    payload.configuration_id = existing.configuration_id;
    payload.based_on_version = existing.version;
  }
  const draft = expect(await api(page, "POST", "/configurations", { token, body: payload }), 201, "crear configuración baseline H12");
  const run = expect(await api(page, "POST", "/test-runs", {
    token,
    body: {
      name: `H12 E2E baseline config v${draft.version}`,
      dataset_name: datasetName,
      sample_size: 1,
      config: {
        max_feedback_iterations: 0,
        configuration_ref: { configuration_id: draft.configuration_id, version: draft.version },
      },
    },
  }), 202, "probar configuración baseline H12");
  const deadline = Date.now() + 240_000;
  let completed;
  while (Date.now() < deadline) {
    completed = expect(await api(page, "GET", `/test-runs/${run.test_run_id}`, { token }), 200, "esperar prueba de configuración H12");
    if (completed.status === "SUCCEEDED") break;
    if (completed.status === "FAILED") throw new Error(`H12_E2E_CONFIG_TEST_FAILED: ${JSON.stringify(completed)}`);
    await page.waitForTimeout(1000);
  }
  if (completed?.status !== "SUCCEEDED") throw new Error(`H12_E2E_CONFIG_TEST_TIMEOUT: ${JSON.stringify(completed)}`);
  expect(await api(page, "POST", `/configurations/${draft.configuration_id}/versions/${draft.version}/activate`, { token }), 200, "activar configuración baseline H12");
  return {
    original_configuration_id: active.configuration_id,
    original_version: active.version,
    temporary_configuration_id: draft.configuration_id,
    temporary_version: draft.version,
    dataset_name: datasetName,
    baseline_model_id: baseline.id || baseline.model_id,
  };
}

export async function restoreH12BaselineConfiguration({ page, token, api, state }) {
  const restored = await api(page, "POST", `/configurations/${state.original_configuration_id}/versions/${state.original_version}/activate`, { token });
  if (restored.status !== 200) throw new Error(`H12_E2E_CONFIG_RESTORE_FAILED: ${JSON.stringify(restored)}`);
  const deleted = await api(page, "DELETE", `/datasets/${state.dataset_name}`, { token });
  if (![200, 202].includes(deleted.status)) throw new Error(`H12_E2E_DATASET_CLEANUP_FAILED: ${JSON.stringify(deleted)}`);
}

async function uploadTestDataset(page, token, sourceRow) {
  const datasetName = `h12-baseline-config-${randomUUID()}`;
  const headers = Object.keys(sourceRow);
  const csvCell = (value) => {
    const normalized = value && typeof value === "object" ? JSON.stringify(value) : String(value ?? "");
    return `"${normalized.replaceAll('"', '""')}"`;
  };
  const csv = [headers.map(csvCell).join(","), headers.map((key) => csvCell(sourceRow[key])).join(",")].join("\n");
  const result = await page.evaluate(async ({ datasetName, token, csv }) => {
    const form = new FormData();
    form.append("file", new Blob([csv], { type: "text/csv" }), `${datasetName}.csv`);
    const response = await fetch("/api/v0/datasets", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    const raw = await response.text();
    let payload = raw;
    try { payload = raw ? JSON.parse(raw) : null; } catch {}
    return { status: response.status, payload };
  }, { datasetName, token, csv });
  if (result.status !== 202) throw new Error(`H12_E2E_DATASET_UPLOAD_FAILED: ${JSON.stringify(result)}`);
  return datasetName;
}
