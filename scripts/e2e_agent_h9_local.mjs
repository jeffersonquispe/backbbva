import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { writeFileSync } from "node:fs";
import { chromium } from "../../frontend_mockup/node_modules/playwright/index.mjs";

const BASE_URL = (process.env.E2E_BASE_URL || "http://localhost").replace(/\/$/, "");
const API_PREFIX = "/api/v0";
const PROJECT = process.env.LOCAL_DOCKER_PROJECT || "aria-local";
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const FRONTEND = resolve(ROOT, "../frontend_mockup");
let browser;
let originalSettings;
let managerToken;

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
  execFileSync("docker", ["compose", "restart", "web"], { cwd: FRONTEND, encoding: "utf8" });
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
  const email = `e2e-h9-${role}-${randomUUID()}@example.com`;
  expect(await api(page, "POST", "/auth/users", {
    bootstrap,
    body: { email, password, name: `Agent H9 ${role}`, role },
  }), 201, `crear usuario ${role}`);
  return expect(await api(page, "POST", "/auth/login", {
    body: { email, password },
  }), 200, `login ${role}`).access_token;
}

async function main() {
  const currentBootstrap = bootstrapToken();
  const bootstrap = currentBootstrap || randomUUID();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  if (!currentBootstrap) {
    compose(["up", "-d", "--force-recreate", "api"], { AUTH_BOOTSTRAP_TOKEN: bootstrap });
    await restartNginx();
    await waitForApi(page);
  }

  try {
    managerToken = await createUser(page, bootstrap, "manager");
    const channelToken = await createUser(page, bootstrap, "channel_manager");
    originalSettings = expect(await api(page, "GET", "/assistant-optimizer-settings", { token: managerToken }), 200, "leer settings");
    expect(await api(page, "PUT", "/assistant-optimizer-settings", {
      token: managerToken,
      body: { settings: {
        ...originalSettings,
        optimizer_enabled: true,
        optimizer_max_budget_renewals: 1,
        max_sessions_per_user: 100,
      } },
    }), 200, "habilitar optimizer para E2E");

    const session = expect(await api(page, "POST", "/agent/sessions", {
      token: channelToken,
      body: {
        mode: "optimization",
        scope: ["model"],
        requested_budget: { tokens: 3000, usd_micros: 3000000, seconds: 180 },
      },
    }), 201, "crear sesión de optimización");
    const activeObjective = expect(await api(page, "GET", "/agent/objectives/active", {
      token: managerToken,
    }), 200, "leer objetivo activo");
    const protectedSegments = activeObjective.schema_mapping?.protected_segments || {};
    if (
      !Object.values(protectedSegments).some((values) =>
        Array.isArray(values) && values.includes("E2E_SUPPORT_29") && values.includes("E2E_SUPPORT_30"),
      )
      || activeObjective.minimum_support_per_segment !== 30
    ) {
      throw new Error(
        `el objetivo activo no fijó los segmentos y el mínimo del fixture: ${JSON.stringify({ protectedSegments, minimum_support_per_segment: activeObjective.minimum_support_per_segment })}`,
      );
    }
    if (
      session.objective_id !== activeObjective.objective_id ||
      session.objective_version !== activeObjective.version
    ) {
      throw new Error("la sesión no fijó la versión activa del objetivo global");
    }
    const sessionId = session.session_id;
    expect(await api(page, "POST", `/agent/sessions/${sessionId}/start`, { token: channelToken }), 200, "iniciar optimizador");

    const deadline = Date.now() + 240_000;
    let claims = [];
    let hypotheses = [];
    let iterations = [];
    let packages = [];
    let experiments = [];
    while (Date.now() < deadline) {
      claims = expect(await api(page, "GET", "/agent/claims/scope%23model", { token: managerToken }), 200, "leer reclamo");
      hypotheses = expect(await api(page, "GET", `/agent/sessions/${sessionId}/hypotheses`, { token: channelToken }), 200, "leer hipótesis");
      iterations = expect(await api(page, "GET", `/agent/sessions/${sessionId}/iterations`, { token: channelToken }), 200, "leer iteraciones");
      packages = expect(await api(page, "GET", `/agent/sessions/${sessionId}/packages`, { token: channelToken }), 200, "leer paquetes de la sesión");
      experiments = expect(await api(page, "GET", `/agent/sessions/${sessionId}/experiments`, { token: channelToken }), 200, "leer experimentos evaluados");
      if (experiments.some((item) => item.status !== "RUNNING") && packages.some((item) => item.status === "VERIFIED")) break;
      const observed = expect(await api(page, "GET", `/agent/sessions/${sessionId}`, { token: channelToken }), 200, "leer estado de sesión");
      if (["STOPPED", "FAILED", "CANCELLED"].includes(observed.status)) break;
      await page.waitForTimeout(1000);
    }
    const hypothesis = hypotheses.find((item) => item.evidence_id);
    if (!hypothesis || !["VALIDATED", "REFUTED", "NONCONCLUSIVE"].includes(hypothesis.evidence_outcome)) {
      throw new Error("la hipótesis no conservó el resultado de la evaluación del especialista");
    }
    const iteration = iterations.find((item) => item.hypothesis === hypothesis.statement);
    if (!iteration) {
      throw new Error(`la iteración no conservó la hipótesis priorizada: ${JSON.stringify(iterations)}`);
    }
    if (
      iteration.specialist !== "xgboost" ||
      !iteration.specialist_verified ||
      iteration.verification_status !== "PASSED"
    ) {
      throw new Error(`la selección/verificación del especialista no coincide: ${JSON.stringify(iteration)}`);
    }
    if (!packages.some((item) => item.status === "VERIFIED")) {
      throw new Error("la propuesta del proveedor no quedó verificada");
    }
    const experiment = experiments.find((item) => item.iteration_number === iteration.number);
    if (!experiment || !["SUCCEEDED", "REJECTED_GLOBAL_CONSTRAINT"].includes(experiment.status)) {
      throw new Error(`el loop no terminó la evaluación reproducible: ${JSON.stringify(experiment || experiments)}`);
    }
    if (
      experiment.components.length !== 4 ||
      experiment.baseline_components.length !== 4 ||
      new Set(experiment.components.map((item) => item.component)).size !== 4 ||
      new Set(experiment.baseline_components.map((item) => item.component)).size !== 4 ||
      !experiment.snapshot_id ||
      !/^[a-f0-9]{64}$/.test(experiment.snapshot_sha256 || "") ||
      experiment.global_evaluation.sample?.partition !== "final" ||
      experiment.global_evaluation.sample?.snapshot_id !== experiment.snapshot_id ||
      experiment.global_evaluation.sample?.content_sha256 !== experiment.snapshot_sha256 ||
      experiment.global_evaluation.knowledge_evidence?.decision_policy !== "evidence_only_v1"
    ) {
      throw new Error(`la evaluación no fijó stack/snapshot/política: ${JSON.stringify(experiment)}`);
    }
    const publishedSegments = experiment.global_evaluation.segments || {};
    if (Object.values(publishedSegments).some((segment) => segment.support < 30)) {
      throw new Error("la evaluación publicó un segmento con menos de 30 casos");
    }
    const support29 = Object.entries(publishedSegments).find(([name]) =>
      name.endsWith("E2E_SUPPORT_29"),
    );
    const support30 = Object.entries(publishedSegments).find(([name]) =>
      name.endsWith("E2E_SUPPORT_30"),
    );
    if (support29) {
      throw new Error(`el segmento de 29 casos no fue suprimido: ${support29[0]}`);
    }
    if (!support30 || support30[1].support !== 30) {
      throw new Error(
        `el segmento de 30 casos no se publicó con soporte exacto: ${JSON.stringify(publishedSegments)}`,
      );
    }
    if (
      !experiment.global_evaluation.metrics?.candidate ||
      !experiment.global_evaluation.metrics?.baseline ||
      !experiment.global_evaluation.delta ||
      experiment.global_evaluation.uncertainty?.method !== "paired_bootstrap" ||
      experiment.global_evaluation.uncertainty?.confidence_level !== 0.95
    ) {
      throw new Error(`la evaluación no incluye comparación pareada completa: ${JSON.stringify(experiment.global_evaluation)}`);
    }
    const segmentSupports = Object.fromEntries(
      Object.entries(publishedSegments).map(([name, segment]) => [name, segment.support]),
    );
    const modelPin = experiment.components.find((item) => item.component === "model");
    const candidateModel = expect(await api(page, "GET", `/models/${modelPin.entity_id}`, { token: managerToken }), 200, "comprobar modelo candidato");
    if (candidateModel.active) {
      throw new Error("un resultado SUCCEEDED de experimento activó el candidato sin promoción");
    }
    if (
      iteration.objective_id !== session.objective_id ||
      iteration.objective_version !== session.objective_version
    ) {
      throw new Error("la iteración no conservó la versión fijada del objetivo");
    }

    let current = expect(await api(page, "GET", `/agent/sessions/${sessionId}`, { token: channelToken }), 200, "leer sesión");
    if (current.status === "ACTIVE") {
      current = expect(await api(page, "POST", `/agent/sessions/${sessionId}/cancel`, {
        token: channelToken,
      }), 200, "cancelar sesión tras verificar propuesta");
    }
    if (current.status !== "CANCELLED") {
      throw new Error(`la sesión no se canceló tras validar el paquete candidato: ${current.status}`);
    }
    const audit = expect(await api(page, "GET", `/agent/sessions/${sessionId}/audit?limit=100`, {
      token: channelToken,
    }), 200, "leer auditoría real de la sesión");
    const auditCategories = new Set(audit.items.map((event) => event.category));
    for (const category of ["session", "iteration", "tool", "lease"]) {
      if (!auditCategories.has(category)) {
        throw new Error(`falta el evento real de auditoría ${category}: ${JSON.stringify([...auditCategories])}`);
      }
    }
    const auditFirstPage = expect(
      await api(page, "GET", `/agent/sessions/${sessionId}/audit?limit=1`, {
        token: channelToken,
      }),
      200,
      "leer primera página de auditoría",
    );
    if (!auditFirstPage.next_cursor || auditFirstPage.items.length !== 1) {
      throw new Error("la auditoría real no devolvió cursor para la segunda página");
    }
    const auditSecondPage = expect(
      await api(
        page,
        "GET",
        `/agent/sessions/${sessionId}/audit?limit=1&cursor=${encodeURIComponent(auditFirstPage.next_cursor)}`,
        { token: channelToken },
      ),
      200,
      "leer segunda página de auditoría",
    );
    if (
      auditSecondPage.items.length !== 1 ||
      auditSecondPage.items[0].event_id === auditFirstPage.items[0].event_id
    ) {
      throw new Error("la segunda página de auditoría no avanzó a otro evento");
    }
    await page.evaluate((token) => localStorage.setItem("aria.auth.accessToken", token), channelToken);
    await page.goto(`${BASE_URL}/configuracion`, { waitUntil: "domcontentloaded" });
    await page.getByRole("button", { name: "Abrir asistente ARIA" }).click();
    await page.getByRole("button", { name: "Optimizador", exact: true }).click();
    const comparisonPanel = page.getByRole("region", {
      name: "Comparación baseline y experimentos",
    });
    await comparisonPanel.waitFor({ state: "visible", timeout: 15_000 });
    await comparisonPanel
      .getByText(`Experimento ${experiment.iteration_number} · ${experiment.status}`, {
        exact: true,
      })
      .waitFor({ state: "visible", timeout: 30_000 });
    const comparisonText = await comparisonPanel.innerText();
    const visibleValues = [
      `Experimento ${experiment.iteration_number} · ${experiment.status}`,
      experiment.snapshot_id,
      experiment.snapshot_sha256,
      "Baseline:",
      "Candidato:",
      "paired_bootstrap",
    ];
    for (const value of visibleValues) {
      if (!comparisonText.includes(value)) {
        throw new Error(`la UI no muestra la evidencia evaluada ${value}: ${comparisonText}`);
      }
    }
    const leasePanel = page.getByLabel("Estado del lease");
    await leasePanel.waitFor({ state: "visible", timeout: 15_000 });
    if (!current.lease || !(await leasePanel.innerText()).includes(current.lease.status)) {
      throw new Error(`la UI no muestra el lease real: ${JSON.stringify(current.lease)}`);
    }
    const auditPanel = page.getByRole("region", { name: "Auditoría de sesión" });
    await auditPanel.waitFor({ state: "visible", timeout: 15_000 });
    await auditPanel
      .getByText(/· experiment ·/)
      .first()
      .waitFor({ state: "visible", timeout: 30_000 });
    const auditText = await auditPanel.innerText();
    for (const category of ["session", "iteration", "tool", "lease", "experiment"]) {
      if (!auditText.includes(`· ${category} ·`)) {
        throw new Error(`la UI no muestra el evento real ${category}: ${auditText}`);
      }
    }
    claims = expect(await api(page, "GET", "/agent/claims/scope%23model", { token: managerToken }), 200, "leer reclamos tras pausar");
    if (claims.some((claim) => claim.session_id === sessionId)) {
      throw new Error("una sesión detenida conserva un reclamo activo");
    }
    const evidence = {
      result: "H11 Playwright por nginx completado",
      session_id: sessionId,
      experiment_id: experiment.experiment_id,
      experiment_status: experiment.status,
      snapshot_id: experiment.snapshot_id,
      snapshot_sha256: experiment.snapshot_sha256,
      component_types: experiment.components.map((item) => item.component).sort(),
      baseline_component_types: experiment.baseline_components.map((item) => item.component).sort(),
      partition: experiment.global_evaluation.sample.partition,
      knowledge_decision_policy: experiment.global_evaluation.knowledge_evidence.decision_policy,
      published_segment_count: Object.keys(publishedSegments).length,
      minimum_published_segment_support: Math.min(30, ...Object.values(publishedSegments).map((segment) => segment.support)),
      published_segment_supports: segmentSupports,
      audit_categories: [...auditCategories].sort(),
      ui_experiment_rendered: true,
      ui_audit_categories: ["session", "iteration", "tool", "lease", "experiment"],
      candidate_active: candidateModel.active,
    };
    console.log(JSON.stringify(evidence));
    if (process.env.H12_E2E_RESULT_PATH) {
      writeFileSync(process.env.H12_E2E_RESULT_PATH, `${JSON.stringify(evidence)}\n`, { mode: 0o600 });
    }
  } finally {
    if (managerToken && originalSettings) {
      await api(page, "PUT", "/assistant-optimizer-settings", {
        token: managerToken,
        body: { settings: originalSettings },
      });
    }
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
