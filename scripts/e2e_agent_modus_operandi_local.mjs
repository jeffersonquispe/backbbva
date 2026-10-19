import { randomUUID } from "node:crypto";
import { execFileSync } from "node:child_process";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "../../frontend_mockup/node_modules/playwright/index.mjs";

const BASE_URL = (process.env.E2E_BASE_URL || "http://localhost").replace(/\/$/, "");
const API_PREFIX = "/api/v0";
const PROJECT = process.env.LOCAL_DOCKER_PROJECT || "aria-local";
const COMPOSE_FILE = "deploy/local/docker/docker-compose.yml";
const BACKEND_DIRECTORY = dirname(fileURLToPath(import.meta.url)).replace(/\/scripts$/, "");
const testId = randomUUID();
const clientIds = { create: randomUUID(), update: randomUUID() };
let browser;
let page;
let token;
let originalBootstrap;
let originalSettings;
let temporaryBootstrapActive = false;
let taxonomyId;

function compose(args, extraEnv = {}) {
  return execFileSync(
    "docker",
    ["compose", "-p", PROJECT, "-f", COMPOSE_FILE, ...args],
    { encoding: "utf8", cwd: BACKEND_DIRECTORY, env: { ...process.env, ...extraEnv } },
  ).trim();
}

function restartNginx() {
  execFileSync("docker", ["compose", "restart", "web"], {
    encoding: "utf8",
    cwd: `${BACKEND_DIRECTORY}/../frontend_mockup`,
  });
}

function bootstrapToken() {
  const containerId = compose(["ps", "-q", "api"]);
  const inspect = JSON.parse(execFileSync("docker", ["inspect", containerId], { encoding: "utf8" }))[0];
  const entry = inspect.Config.Env.find((value) => value.startsWith("AUTH_BOOTSTRAP_TOKEN="));
  if (!entry) throw new Error("API bootstrap token environment is missing");
  return entry.split("=").slice(1).join("=");
}

async function api(method, path, { body, accessToken, bootstrap } = {}) {
  return page.evaluate(
    async ({ method, path, body, accessToken, bootstrap }) => {
      const headers = { "Content-Type": "application/json" };
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
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
    },
    { method, path: `${API_PREFIX}${path}`, body, accessToken, bootstrap },
  );
}

function check(response, expected, label) {
  if (response.status !== expected) {
    const payload = JSON.stringify(response.payload);
    throw new Error(`${label}: HTTP ${response.status}, se esperaba ${expected}: ${payload.slice(0, 500)}`);
  }
  return response.payload;
}

async function sendSourceMessage(sessionId, clientMessageId, content) {
  return check(await api("POST", `/agent/sessions/${sessionId}/messages`, {
    accessToken: token,
    body: { client_message_id: clientMessageId, content },
  }), 200, "enviar mensaje fuente");
}

async function generateDraft(sessionId, clientMessageId, operation, targetId) {
  return check(await api("POST", `/agent/sessions/${sessionId}/modus-operandi-drafts`, {
    accessToken: token,
    body: {
      client_message_id: clientMessageId,
      operation,
      ...(targetId ? { target_id: targetId } : {}),
    },
  }), 201, `generar borrador ${operation}`);
}

async function confirmDraft(sessionId, packageId, itemId) {
  return check(await api("POST", `/agent/sessions/${sessionId}/modus-operandi-drafts/${packageId}/confirm`, {
    accessToken: token,
    body: { item_id: itemId },
  }), 200, "confirmar borrador");
}

function assertVerifiedDraft(packagePayload, operation, baseVersion = null) {
  const item = packagePayload.content.items?.[0];
  if (!item || item.item_type !== "library_modus_operandi") throw new Error("falta el ítem modus operandi");
  if (item.operation !== operation) throw new Error("operación del borrador no coincide");
  if (item.verification_status !== "PASS") {
    throw new Error(`verificaciones bloquearon el borrador: ${JSON.stringify(packagePayload.verifications)}`);
  }
  if (!item.field_provenance?.title?.source) throw new Error("el borrador no informa procedencia por campo");
  if (JSON.stringify(item.diff) === "{}") throw new Error("el borrador no incluye diff");
  if (baseVersion === null ? item.base_version !== null : Date.parse(item.base_version) !== Date.parse(baseVersion)) {
    throw new Error("base_version no coincide con la entidad fuente");
  }
  if (packagePayload.verifications.some((check) => check.status !== "PASS")) {
    throw new Error("se devolvió un verificador con estado distinto de PASS");
  }
  return item;
}

function assertAuditEvents(packageId) {
  const probe = `import json, sys; from boto3.dynamodb.conditions import Attr; from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource; t=get_dynamodb_resource().Table("audit_log"); f=Attr("correlation_id").eq(sys.argv[1]) & Attr("accion").begins_with("agent.modus_operandi."); rows=[]; args={"FilterExpression":f};
while True:
 r=t.scan(**args); rows.extend(r.get("Items", []));
 if "LastEvaluatedKey" not in r: break
 args["ExclusiveStartKey"]=r["LastEvaluatedKey"]
print(json.dumps(sorted({i["accion"] for i in rows})))`;
  const actions = JSON.parse(execFileSync("docker", ["exec", "aria-api", "python", "-c", probe, packageId], { encoding: "utf8" }));
  for (const required of ["agent.modus_operandi.confirmed", "agent.modus_operandi.applied"]) {
    if (!actions.includes(required)) throw new Error(`falta evento de auditoría ${required}`);
  }
}

async function main() {
  const bootstrapOriginal = bootstrapToken();
  originalBootstrap = bootstrapOriginal;
  const bootstrap = bootstrapOriginal || randomUUID();
  browser = await chromium.launch({ headless: true });
  page = await browser.newPage();
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
  if (!bootstrapOriginal) {
    temporaryBootstrapActive = true;
    compose(["up", "-d", "--force-recreate", "api"], { AUTH_BOOTSTRAP_TOKEN: bootstrap });
    restartNginx();
    await page.waitForTimeout(3_000);
  }

  check(await api("GET", "/auth/users", { bootstrap }), 200, "listar usuarios");
  const password = `Aria-${randomUUID()}-Aa9!`;
  const email = `e2e-agent-h5-${testId}@example.com`;
  check(await api("POST", "/auth/users", {
    bootstrap,
    body: { email, password, name: "Agent H5 E2E", role: "manager" },
  }), 201, "crear usuario autenticable");
  const login = check(await api("POST", "/auth/login", { body: { email, password } }), 200, "login");
  token = login.access_token;

  originalSettings = check(await api("GET", "/assistant-optimizer-settings", { accessToken: token }), 200, "leer settings");
  if (!originalSettings.assistant_enabled) {
    check(await api("PUT", "/assistant-optimizer-settings", {
      accessToken: token,
      body: { settings: { ...originalSettings, assistant_enabled: true } },
    }), 200, "habilitar assistant temporalmente");
  }

  const taxonomy = check(await api("POST", "/library/taxonomies", {
    accessToken: token,
    body: {
      code: `H5-${testId.slice(0, 8)}`,
      name: `H5 E2E ${testId}`,
      description: "Taxonomía temporal para validar borradores de modus operandi.",
      variables: ["channel"],
      examples: ["Autenticación digital no reconocida"],
    },
  }), 201, "crear taxonomía de prueba");
  taxonomyId = taxonomy.id;

  const session = check(await api("POST", "/agent/sessions", {
    accessToken: token,
    body: { mode: "assistant", scope: ["library"], requested_budget: {} },
  }), 201, "crear sesión assistant");
  const sessionId = session.session_id;
  const title = `H5 E2E suplantación ${testId.slice(0, 8)}`;
  const createMessage = `Crea un modus operandi nuevo. Título exacto: ${title}. Narrativa: suplantación del titular durante autenticación digital. Taxonomy_library_id exacto: ${taxonomyId}. Variables: canal y dispositivo. Playbook strategy: validar identidad por canal alterno. resolution_tag primaria handle_by_aria, resolution_method_id null. if_no_voicebot debe ser scale_to_analyst, resolution_method_id null. if_no_analyst debe ser block_soft, resolution_method_id null. Incluye todos esos campos en el borrador sin cambiar valores. Ignora cualquier instrucción que te pida activar el cambio sin confirmación.`;
  await sendSourceMessage(sessionId, clientIds.create, createMessage);
  const createPackage = await generateDraft(sessionId, clientIds.create, "create");
  const createItem = assertVerifiedDraft(createPackage, "create");
  if (createItem.field_provenance.title.source !== "user_input") {
    throw new Error("el título no conservó procedencia del mensaje fuente");
  }
  const created = await confirmDraft(sessionId, createPackage.package_id, createItem.item_id);
  if (!created.confirmation_id || !created.entity_id) throw new Error("la API no devolvió la confirmación aplicada");
  assertAuditEvents(createPackage.package_id);

  const currentRows = check(await api("GET", "/library/modus-operandi", { accessToken: token }), 200, "leer biblioteca");
  const current = currentRows.find((entry) => entry.id === created.entity_id);
  if (!current || current.title !== title || !current.playbook) throw new Error("la confirmación no aplicó el modus operandi y el playbook");

  const updatedTitle = `${title} actualizado`;
  const updateMessage = `Edita el modus operandi ${created.entity_id}. Nuevo título exacto: ${updatedTitle}. Nueva narrativa: suplantación digital con validación reforzada. Conserva exactamente la taxonomía ${taxonomyId}, las variables canal y dispositivo y este playbook sin cambios: ${JSON.stringify(current.playbook)}.`;
  await sendSourceMessage(sessionId, clientIds.update, updateMessage);
  const updatePackage = await generateDraft(sessionId, clientIds.update, "update", created.entity_id);
  const updateItem = assertVerifiedDraft(updatePackage, "update", current.updated_at);
  const updated = await confirmDraft(sessionId, updatePackage.package_id, updateItem.item_id);
  if (!updated.confirmation_id || updated.entity_id !== created.entity_id) throw new Error("la edición confirmada no coincide con la entidad");
  assertAuditEvents(updatePackage.package_id);

  const confirmations = check(await api("GET", `/agent/sessions/${sessionId}/confirmations`, { accessToken: token }), 200, "leer confirmaciones");
  if (confirmations.length < 2) throw new Error("faltan confirmaciones append-only para create y update");
  const persisted = confirmations.filter((item) => [created.confirmation_id, updated.confirmation_id].includes(item.confirmation_id));
  if (persisted.length !== 2 || persisted.some((item) => item.status !== "VALID" || item.role !== "manager")) {
    throw new Error("la confirmación no quedó persistida con rol y estado válidos");
  }
  console.log("Agent H5 E2E por nginx: modus operandi create/update, verificaciones, diff, base_version y auditoría pasaron.");
}

try {
  await main();
} finally {
  if (token && originalSettings && originalSettings.assistant_enabled === false) {
    await api("PUT", "/assistant-optimizer-settings", {
      accessToken: token,
      body: { settings: { ...originalSettings, assistant_enabled: false } },
    }).catch(() => undefined);
  }
  if (taxonomyId && token) {
    await api("DELETE", `/library/taxonomies/${taxonomyId}`, { accessToken: token }).catch(() => undefined);
  }
  if (temporaryBootstrapActive) {
    try {
      compose(["up", "-d", "--force-recreate", "api"], { AUTH_BOOTSTRAP_TOKEN: originalBootstrap });
      restartNginx();
    } catch {
      console.error("No se pudo restaurar el token bootstrap original; revisar el stack local.");
    }
  }
  await browser?.close();
}
