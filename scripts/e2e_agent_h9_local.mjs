import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
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
    while (Date.now() < deadline) {
      claims = expect(await api(page, "GET", "/agent/claims/scope%23model", { token: managerToken }), 200, "leer reclamo");
      hypotheses = expect(await api(page, "GET", `/agent/sessions/${sessionId}/hypotheses`, { token: channelToken }), 200, "leer hipótesis");
      iterations = expect(await api(page, "GET", `/agent/sessions/${sessionId}/iterations`, { token: channelToken }), 200, "leer iteraciones");
      packages = expect(await api(page, "GET", `/agent/sessions/${sessionId}/packages`, { token: channelToken }), 200, "leer paquetes de la sesión");
      if (iterations.some((item) => item.experiment_verified === true) && packages.some((item) => item.status === "VERIFIED")) break;
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
      !iteration.experiment_verified ||
      iteration.verification_status !== "PASSED"
    ) {
      throw new Error(`la selección/verificación del especialista no coincide: ${JSON.stringify(iteration)}`);
    }
    if (!packages.some((item) => item.status === "VERIFIED")) {
      throw new Error("la propuesta del proveedor no quedó verificada");
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
    claims = expect(await api(page, "GET", "/agent/claims/scope%23model", { token: managerToken }), 200, "leer reclamos tras pausar");
    if (claims.some((claim) => claim.session_id === sessionId)) {
      throw new Error("una sesión detenida conserva un reclamo activo");
    }
    console.log("H10 Playwright por nginx: objetivo fijado, propuesta XGBoost generada y verificada, cancelación e hipótesis evaluada pasaron.");
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
