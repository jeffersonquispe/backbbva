import { randomUUID } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../frontend_mockup/node_modules/playwright/index.mjs";

const BASE_URL = (process.env.E2E_BASE_URL || "http://localhost").replace(/\/$/, "");
const API_PREFIX = "/api/v0";
const PROJECT = process.env.LOCAL_DOCKER_PROJECT || "aria-local";
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RESULT_PATH = process.env.H12_E2E_RESULT_PATH || "/tmp/aria-h12-h11-result.json";

function compose(args, extraEnv = {}) {
  return execFileSync("docker", ["compose", "-p", PROJECT, "-f", "deploy/local/docker/docker-compose.yml", ...args], {
    cwd: ROOT,
    encoding: "utf8",
    env: { ...process.env, ...extraEnv },
  }).trim();
}

function bootstrapToken() {
  const containerId = compose(["ps", "-q", "api"]);
  const details = JSON.parse(execFileSync("docker", ["inspect", containerId], { encoding: "utf8" }))[0];
  const entry = details.Config.Env.find((value) => value.startsWith("AUTH_BOOTSTRAP_TOKEN="));
  return entry?.split("=").slice(1).join("=") || "";
}

async function restartNginx() {
  execFileSync("docker", ["compose", "restart", "web"], {
    cwd: resolve(ROOT, "../frontend_mockup"),
    encoding: "utf8",
  });
}

async function waitForApi(page) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const healthy = await page.evaluate(async () => {
      try { return (await fetch("/health")).ok; } catch { return false; }
    });
    if (healthy) return;
    await page.waitForTimeout(500);
  }
  throw new Error("API no volvió a estar saludable por nginx");
}

async function api(page, method, path, { body, token, bootstrap } = {}) {
  return page.evaluate(async ({ method, path, body, token, bootstrap }) => {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (bootstrap) headers["X-Bootstrap-Token"] = bootstrap;
    const response = await fetch(path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const raw = await response.text();
    let payload = raw;
    try { payload = raw ? JSON.parse(raw) : null; } catch {}
    return { status: response.status, payload };
  }, { method, path: `${API_PREFIX}${path}`, body, token, bootstrap });
}

function expect(response, status, label) {
  if (response.status !== status) {
    throw new Error(`${label}: HTTP ${response.status}, esperado ${status}: ${JSON.stringify(response.payload)}`);
  }
  return response.payload;
}

async function createUser(page, bootstrap, role) {
  const password = `Aria-${randomUUID()}-Aa9!`;
  const email = `e2e-h12-${role}-${randomUUID()}@example.com`;
  expect(await api(page, "POST", "/auth/users", {
    bootstrap,
    body: { email, password, name: `Agent H12 ${role}`, role },
  }), 201, `crear usuario ${role}`);
  return expect(await api(page, "POST", "/auth/login", {
    body: { email, password },
  }), 200, `login ${role}`).access_token;
}

async function openOptimizerUi(page, token) {
  await page.evaluate((accessToken) => localStorage.setItem("aria.auth.accessToken", accessToken), token);
  await page.goto(`${BASE_URL}/configuracion`, { waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "Abrir asistente ARIA" }).click();
  await page.getByRole("button", { name: "Optimizador", exact: true }).click();
}

async function createAndWaitReviewAlert(page, managerToken, index) {
  const eventId = `H12-${randomUUID()}`;
  const start = expect(await api(page, "POST", "/alerts/test", {
    token: managerToken,
    body: {
      origin: "manual",
      created_by: "h12-e2e-local",
      event: {
        eventId,
        eventType: "H12 rollout E2E",
        eventid: eventId,
        eventtype: "H12 rollout E2E",
        customerId: `H12-CUSTOMER-${index}-${randomUUID()}`,
        customerid: `H12-CUSTOMER-${index}-${randomUUID()}`,
        channel: "H12-E2E",
        integrationpoint: "H12-review-worker",
        amount_value: 1275 + index,
        fecha_transaccion: new Date().toISOString(),
      },
    },
  }), 202, `despachar alerta H12 ${index}`);
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    const operation = expect(await api(page, "GET", `/async-operations/${start.async_operation_id}/poll`, {
      token: managerToken,
    }), 200, `consultar workflow H12 ${index}`);
    if (operation.done) {
      if (operation.status !== "SUCCEEDED") {
        throw new Error(`review worker no completó alerta ${index}: ${JSON.stringify(operation)}`);
      }
      return { alert_id: start.alert_id, workflow_execution_id: start.workflow_execution_id };
    }
    await page.waitForTimeout(1000);
  }
  throw new Error(`timeout esperando review worker para alerta ${index}`);
}

async function collectRealStageObservations(page, managerToken, releaseId, stage) {
  const observedAlerts = [];
  const maximumAlerts = 35;
  for (let index = 0; index < maximumAlerts; index += 1) {
    observedAlerts.push(await createAndWaitReviewAlert(page, managerToken, index));
    const release = expect(await api(page, "GET", `/agent/releases/${releaseId}`, {
      token: managerToken,
    }), 200, `leer observaciones de ${stage}`);
    const count = Number(release.observations?.count || 0);
    const disagreements = Number(release.observations?.disagreements || 0);
    if (count >= 30) {
      if (disagreements * 100 > count * 5) {
        throw new Error(`${stage}: desacuerdo ${disagreements}/${count} excede 5 %`);
      }
      return { status: release.status, count, disagreements, processed_alerts: observedAlerts };
    }
  }
  const release = expect(await api(page, "GET", `/agent/releases/${releaseId}`, {
    token: managerToken,
  }), 200, `diagnóstico de guardrail ${stage}`);
  throw new Error(`${stage}: solo ${release.observations?.count || 0}/30 observaciones tras ${maximumAlerts} alertas por review worker`);
}

async function main() {
  const h11 = JSON.parse(readFileSync(RESULT_PATH, "utf8"));
  if (h11.experiment_status !== "SUCCEEDED" || !h11.session_id || !h11.experiment_id) {
    throw new Error(`H11 debe dejar experimento SUCCEEDED identificable: ${JSON.stringify(h11)}`);
  }
  const currentBootstrap = bootstrapToken();
  const bootstrap = currentBootstrap || randomUUID();

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  let managerToken;
  let releaseForCleanup;
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  try {
    if (!currentBootstrap) {
      compose(["up", "-d", "--force-recreate", "api"], { AUTH_BOOTSTRAP_TOKEN: bootstrap });
      await restartNginx();
    }
    await waitForApi(page);
    managerToken = await createUser(page, bootstrap, "manager");
    if (process.env.H12_E2E_CLEANUP === "1") {
      const releases = expect(await api(page, "GET", "/agent/releases", {
        token: managerToken,
      }), 200, "listar releases para limpiar E2E local");
      const active = releases.filter((item) => [
        "SHADOW", "PENDING_APPROVAL", "CANARY_5", "CANARY_25", "CANARY_50", "FULL",
      ].includes(item.status));
      const cleaned = [];
      for (const item of active) {
        const result = expect(await api(page, "POST", `/agent/releases/${item.release_id}/rollback`, {
          token: managerToken,
          body: { expected_version: item.version, reason: "Limpieza de release local incompleto del E2E H12" },
        }), 200, `rollback de release incompleto ${item.release_id}`);
        cleaned.push({ release_id: result.release_id, status: result.status });
      }
      process.stdout.write(`${JSON.stringify({ result: "H12 E2E cleanup local", cleaned })}\n`);
      return;
    }
    const activeConfiguration = expect(await api(page, "GET", "/configurations/active", {
      token: managerToken,
    }), 200, "leer configuración activa para rollout H12");
    const xgboostSegments = Object.entries(activeConfiguration.segments || {}).filter(([, segment]) =>
      segment.enabled && segment.agent?.detector?.use_xgboost_model && segment.agent?.detector?.xgboost_model_id,
    ).map(([name, segment]) => ({ name, model_id: segment.agent.detector.xgboost_model_id }));
    if (process.env.H12_E2E_FULL === "1" && xgboostSegments.length === 0) {
      throw new Error(`H12_E2E_PRECONDITION_XGBOOST_DISABLED: la configuración ${activeConfiguration.configuration_id}@${activeConfiguration.version} no habilita XGBoost en segmentos activos; el review worker no ejecutará el scorer ni puede producir observaciones válidas.`);
    }
    if (process.env.H12_E2E_INSPECT === "1") {
      const activeConfigurationEvidence = {
        active_configuration_id: activeConfiguration.configuration_id,
        active_configuration_version: activeConfiguration.version,
        segments: Object.fromEntries(Object.entries(activeConfiguration.segments || {}).map(([name, segment]) => [name, {
          enabled: segment.enabled,
          use_xgboost_model: segment.agent?.detector?.use_xgboost_model,
          xgboost_model_id: segment.agent?.detector?.xgboost_model_id,
        }])),
      };
      writeFileSync("/tmp/aria-h12-active-config.json", `${JSON.stringify(activeConfigurationEvidence)}\n`, { mode: 0o600 });
      process.stdout.write(`${JSON.stringify(activeConfigurationEvidence)}\n`);
      return;
    }
    const channelToken = await createUser(page, bootstrap, "channel_manager");
    await openOptimizerUi(page, channelToken);
    await page.getByLabel("Sesión evaluada").fill(h11.session_id);
    await page.getByLabel("Experimento evaluado").fill(h11.experiment_id);
    const validationResponse = page.waitForResponse((response) =>
      response.url().endsWith("/agent/releases/retrospective-validations") && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Validar retrospectivamente" }).click();
    const validationResult = await validationResponse;
    const validation = expect({ status: validationResult.status(), payload: await validationResult.json() }, 201, "validación retrospectiva UI");
    if (
      validation.status !== "PASSED" ||
      validation.snapshot_id !== h11.snapshot_id ||
      validation.snapshot_sha256 !== h11.snapshot_sha256 ||
      validation.component_pins.length !== 4
    ) {
      throw new Error(`retrospectiva no reproduce snapshot y cuatro pins: ${JSON.stringify(validation)}`);
    }
    if (process.env.H12_E2E_FULL === "1") {
      const baselineModel = validation.baseline_component_pins.find((pin) => pin.component === "model");
      if (!baselineModel || !xgboostSegments.some((segment) => segment.model_id === baselineModel.entity_id)) {
        throw new Error(`H12_E2E_PRECONDITION_BASELINE_MODEL_MISMATCH: los segmentos XGBoost activos ${JSON.stringify(xgboostSegments)} no fijan el modelo baseline de la validación ${baselineModel?.entity_id || "missing"}.`);
      }
    }
    const priorReleases = expect(await api(page, "GET", "/agent/releases", {
      token: managerToken,
    }), 200, "listar releases para aislar el fixture H12");
    for (const prior of priorReleases.filter((item) =>
      item.session_id === h11.session_id &&
      item.experiment_id === h11.experiment_id &&
      item.title === "H12 local candidate" &&
      !["ROLLED_BACK", "REJECTED", "FAILED"].includes(item.status)
    )) {
      expect(await api(page, "POST", `/agent/releases/${prior.release_id}/rollback`, {
        token: managerToken,
        body: {
          expected_version: prior.version,
          reason: "Limpiar release activo previo del mismo fixture H12 local",
        },
      }), 200, "rollback de release activo previo del fixture H12");
    }
    await page.getByLabel("Título del release").fill("H12 local candidate");
    await page.getByLabel("Motivo", { exact: true }).fill("E2E de retrospectiva y shadow con experimento H11 real local");
    const releaseResponse = page.waitForResponse((response) =>
      response.url().endsWith("/agent/releases") && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Crear en SHADOW" }).click();
    const releaseResult = await releaseResponse;
    const release = expect({ status: releaseResult.status(), payload: await releaseResult.json() }, 201, "crear release SHADOW UI");
    releaseForCleanup = release;
    if (
      release.status !== "SHADOW" ||
      Number(release.observations?.count || 0) !== 0 ||
      release.rollout_policy_version !== "h12_model_only_v1"
    ) {
      throw new Error(`release debe iniciar en SHADOW sin observaciones: ${JSON.stringify(release)}`);
    }
    const candidate = release.candidate_component_pins.find((pin) => pin.component === "model");
    if (!candidate) throw new Error("release sin pin de modelo candidato");
    const candidateModel = expect(await api(page, "GET", `/models/${candidate.entity_id}`, {
      token: managerToken,
    }), 200, "verificar candidato inactivo");
    if (candidateModel.active) throw new Error("request SHADOW activó el modelo candidato");
    const denied = await api(page, "POST", `/agent/releases/${release.release_id}/approve`, {
      token: channelToken,
      body: { expected_version: release.version, reason: "No autorizado" },
    });
    if (denied.status !== 403) throw new Error(`channel_manager aprobó release: ${JSON.stringify(denied)}`);

    if (process.env.H12_E2E_PROBE === "1") {
      const probeAlert = await createAndWaitReviewAlert(page, managerToken, 0);
      const afterReview = expect(await api(page, "GET", `/agent/releases/${release.release_id}`, {
        token: managerToken,
      }), 200, "leer observación tras review worker real");
      const rolledBack = expect(await api(page, "POST", `/agent/releases/${release.release_id}/rollback`, {
        token: managerToken,
        body: { expected_version: release.version, reason: "Cierre de preflight local del review worker" },
      }), 200, "rollback de preflight local");
      releaseForCleanup = rolledBack;
      process.stdout.write(`${JSON.stringify({
        result: "H12 probe por nginx con alerta real procesada",
        deployment: false,
        alert_id: probeAlert.alert_id,
        workflow_execution_id: probeAlert.workflow_execution_id,
        observations_after_worker: afterReview.observations,
        active_release_status: release.status,
        final_status: rolledBack.status,
        limitation: "la configuración activa local no usa XGBoost; se observó en el contrato de configuración activa y este flujo no puede producir shadow observations sin scorer habilitado",
      })}\n`);
      return;
    }

    if (process.env.H12_E2E_FULL !== "1") {
    const guarded = await api(page, "POST", `/agent/releases/${release.release_id}/submit`, {
      token: channelToken,
      body: { expected_version: release.version, reason: "Observaciones insuficientes" },
    });
    if (guarded.status !== 409 || guarded.payload?.detail !== "GUARDRAIL_NOT_MET") {
      throw new Error(`se permitió salir de SHADOW sin 30 observaciones: ${JSON.stringify(guarded)}`);
    }
    await openOptimizerUi(page, managerToken);
    await page.getByText("H12 local candidate · SHADOW", { exact: true }).waitFor({ state: "visible", timeout: 15_000 });
    const rollbackResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/agent/releases/${release.release_id}/rollback`) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Rollback", exact: true }).click();
    const rollbackResult = await rollbackResponse;
    const rolledBack = expect({ status: rollbackResult.status(), payload: await rollbackResult.json() }, 200, "rollback desde UI por manager");
    releaseForCleanup = rolledBack;
    if (rolledBack.status !== "ROLLED_BACK") throw new Error(`rollback no persistido: ${JSON.stringify(rolledBack)}`);
    const afterRollback = expect(await api(page, "GET", `/models/${candidate.entity_id}`, {
      token: managerToken,
    }), 200, "verificar modelo tras rollback");
    if (afterRollback.active) throw new Error("el modelo candidato quedó activo tras rollback");

    console.log(JSON.stringify({
      result: "H12 E2E integrado local por nginx completado",
      deployment: false,
      production_performance_evidence: false,
      h11_experiment_id: h11.experiment_id,
      snapshot_id: validation.snapshot_id,
      snapshot_sha256: validation.snapshot_sha256,
      validation_status: validation.status,
      validation_created_in_ui: true,
      candidate_pin_count: validation.component_pins.length,
      release_id: release.release_id,
      rollout_policy_version: release.rollout_policy_version,
      observed_statuses: ["SHADOW", "ROLLED_BACK"],
      release_created_in_ui: true,
      rollback_executed_in_ui: true,
      channel_manager_approval_http: denied.status,
      submit_without_30_observations_http: guarded.status,
      candidate_active_before_and_after: false,
      limitation: "La promoción gradual requiere 30 observaciones producidas por alertas reales del camino review; este escenario verifica el guardrail sin inyectar observaciones ficticias.",
    }));
    return;
    }

    const stages = [];
    stages.push(await collectRealStageObservations(page, managerToken, release.release_id, "SHADOW"));
    const submitResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/agent/releases/${release.release_id}/submit`) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Enviar a aprobación" }).click();
    const submitResult = await submitResponse;
    const submitted = expect({ status: submitResult.status(), payload: await submitResult.json() }, 200, "enviar SHADOW a aprobación desde UI");
    await openOptimizerUi(page, managerToken);
    await page.getByText("H12 local candidate · PENDING_APPROVAL", { exact: true }).waitFor({ state: "visible", timeout: 15_000 });
    const approveResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/agent/releases/${release.release_id}/approve`) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Aprobar · manager" }).click();
    const approveResult = await approveResponse;
    const approved = expect({ status: approveResult.status(), payload: await approveResult.json() }, 200, "aprobar CANARY_5 como manager desde UI");
    let current = approved;
    for (const target of ["CANARY_25", "CANARY_50", "FULL"]) {
      stages.push(await collectRealStageObservations(page, managerToken, release.release_id, current.status));
      const advanceResponse = page.waitForResponse((response) =>
        response.url().endsWith(`/agent/releases/${release.release_id}/advance`) && response.request().method() === "POST",
      );
      const advanceButton = page.getByRole("button", { name: `Avanzar a ${target}` });
      await advanceButton.waitFor({ state: "visible", timeout: 15_000 });
      await page.waitForFunction((label) => {
        const button = Array.from(document.querySelectorAll("button")).find((item) => item.textContent?.trim() === label);
        return Boolean(button && !button.disabled);
      }, `Avanzar a ${target}`, { timeout: 20_000 });
      await advanceButton.click();
      const advanceResult = await advanceResponse;
      current = expect({ status: advanceResult.status(), payload: await advanceResult.json() }, 200, `avanzar a ${target} desde UI`);
    }
    stages.push(await collectRealStageObservations(page, managerToken, release.release_id, "FULL"));
    const fullRollbackResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/agent/releases/${release.release_id}/rollback`) && response.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Rollback", exact: true }).click();
    const fullRollbackResult = await fullRollbackResponse;
    const rolledBack = expect({ status: fullRollbackResult.status(), payload: await fullRollbackResult.json() }, 200, "rollback posterior a FULL desde UI");
    releaseForCleanup = rolledBack;
    const finalCandidate = expect(await api(page, "GET", `/models/${candidate.entity_id}`, {
      token: managerToken,
    }), 200, "confirmar candidato tras rollback de FULL");
    if (rolledBack.status !== "ROLLED_BACK" || finalCandidate.active) {
      throw new Error("rollback posterior a FULL no retiró el candidato");
    }
    console.log(JSON.stringify({
      result: "H12 FULL E2E local por nginx completado con review worker",
      deployment: false,
      production_performance_evidence: false,
      h11_experiment_id: h11.experiment_id,
      snapshot_id: validation.snapshot_id,
      snapshot_sha256: validation.snapshot_sha256,
      validation_status: validation.status,
      release_id: release.release_id,
      rollout_policy_version: release.rollout_policy_version,
      stage_observations: stages.map(({ status, count, disagreements, processed_alerts }) => ({
        stage: status, count, disagreements,
        disagreement_pct: Number((disagreements * 100 / count).toFixed(2)),
        review_worker_alerts: processed_alerts.length,
      })),
      approved_statuses: [approved.status, "CANARY_25", "CANARY_50", "FULL"],
      approval_and_advancement_in_ui: true,
      channel_manager_approval_http: denied.status,
      final_status: rolledBack.status,
      candidate_active_after_rollback: finalCandidate.active,
      alert_origin: "POST /api/v0/alerts/test -> Celery review worker",
    }));
  } finally {
    if (managerToken && releaseForCleanup && releaseForCleanup.status !== "ROLLED_BACK") {
      await api(page, "POST", `/agent/releases/${releaseForCleanup.release_id}/rollback`, {
        token: managerToken,
        body: {
          expected_version: releaseForCleanup.version,
          reason: "Limpieza del escenario E2E H12 tras fallo",
        },
      });
    }
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
