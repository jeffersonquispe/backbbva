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
let assistantTaxonomyId;
let similarCaseId;
let watchlistId;
let flagId;

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

function assertTaxonomyAuditEvents(packageId) {
  const probe = `import json, sys; from boto3.dynamodb.conditions import Attr; from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource; t=get_dynamodb_resource().Table("audit_log"); f=Attr("correlation_id").eq(sys.argv[1]) & Attr("accion").begins_with("agent.taxonomy."); rows=[]; args={"FilterExpression":f};
while True:
 r=t.scan(**args); rows.extend(r.get("Items", []));
 if "LastEvaluatedKey" not in r: break
 args["ExclusiveStartKey"]=r["LastEvaluatedKey"]
print(json.dumps(sorted({i["accion"] for i in rows})))`;
  const actions = JSON.parse(execFileSync("docker", ["exec", "aria-api", "python", "-c", probe, packageId], { encoding: "utf8" }));
  for (const required of ["agent.taxonomy.confirmed", "agent.taxonomy.applied"]) {
    if (!actions.includes(required)) throw new Error(`falta evento de auditoría ${required}`);
  }
}

function assertSimilarCaseAuditEvents(packageId) {
  const probe = `import json, sys; from boto3.dynamodb.conditions import Attr; from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource; t=get_dynamodb_resource().Table("audit_log"); f=Attr("correlation_id").eq(sys.argv[1]) & Attr("accion").begins_with("agent.similar_case."); rows=[]; args={"FilterExpression":f};
while True:
 r=t.scan(**args); rows.extend(r.get("Items", []));
 if "LastEvaluatedKey" not in r: break
 args["ExclusiveStartKey"]=r["LastEvaluatedKey"]
print(json.dumps(sorted({i["accion"] for i in rows})))`;
  const actions = JSON.parse(execFileSync("docker", ["exec", "aria-api", "python", "-c", probe, packageId], { encoding: "utf8" }));
  for (const required of ["agent.similar_case.confirmed", "agent.similar_case.applied"]) {
    if (!actions.includes(required)) throw new Error(`falta evento de auditoría ${required}`);
  }
}

function assertWatchlistAuditEvents(packageId) {
  const probe = `import json, sys; from boto3.dynamodb.conditions import Attr; from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource; t=get_dynamodb_resource().Table("audit_log"); f=Attr("correlation_id").eq(sys.argv[1]) & Attr("accion").begins_with("agent.watchlist."); rows=[]; args={"FilterExpression":f};
while True:
 r=t.scan(**args); rows.extend(r.get("Items", []));
 if "LastEvaluatedKey" not in r: break
 args["ExclusiveStartKey"]=r["LastEvaluatedKey"]
print(json.dumps(sorted({i["accion"] for i in rows})))`;
  const actions = JSON.parse(execFileSync("docker", ["exec", "aria-api", "python", "-c", probe, packageId], { encoding: "utf8" }));
  for (const required of ["agent.watchlist.confirmed", "agent.watchlist.applied"]) {
    if (!actions.includes(required)) throw new Error(`falta evento de auditoría ${required}`);
  }
}

function assertFlagAuditEvents(packageId) {
  const probe = `import json, sys; from boto3.dynamodb.conditions import Attr; from src.infrastructure.persistence.database.dynamodb.client import get_dynamodb_resource; t=get_dynamodb_resource().Table("audit_log"); f=Attr("correlation_id").eq(sys.argv[1]) & Attr("accion").begins_with("agent.flag."); rows=[]; args={"FilterExpression":f};
while True:
 r=t.scan(**args); rows.extend(r.get("Items", []));
 if "LastEvaluatedKey" not in r: break
 args["ExclusiveStartKey"]=r["LastEvaluatedKey"]
print(json.dumps(sorted({i["accion"] for i in rows})))`;
  const actions = JSON.parse(execFileSync("docker", ["exec", "aria-api", "python", "-c", probe, packageId], { encoding: "utf8" }));
  for (const required of ["agent.flag.confirmed", "agent.flag.applied"]) {
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

  const taxonomyCreateMessage = randomUUID();
  const taxonomyCode = `H5T-${testId.slice(0, 8)}`;
  const taxonomyName = `Taxonomía asistida ${testId}`;
  await sendSourceMessage(sessionId, taxonomyCreateMessage,
    `Crea una taxonomía de fraude. code exacto ${taxonomyCode}; name exacto ${taxonomyName}; description: Suplantación en autenticación digital; variables: canal y dispositivo; examples: acceso desde dispositivo desconocido.`);
  const taxonomyDraft = check(await api("POST", `/agent/sessions/${sessionId}/taxonomy-drafts`, {
    accessToken: token,
    body: { client_message_id: taxonomyCreateMessage, operation: "create" },
  }), 201, "generar borrador de taxonomía");
  const taxonomyItem = taxonomyDraft.content.items?.[0];
  if (!taxonomyItem || taxonomyItem.item_type !== "library_taxonomy" || taxonomyItem.verification_status !== "PASS") {
    throw new Error(`borrador taxonomía no verificado: ${JSON.stringify(taxonomyDraft.verifications)}`);
  }
  if (!taxonomyItem.diff?.name || !taxonomyItem.field_provenance?.name?.source) {
    throw new Error("borrador taxonomía no incluye diff o procedencia");
  }
  const taxonomyConfirmed = check(await api("POST", `/agent/sessions/${sessionId}/taxonomy-drafts/${taxonomyDraft.package_id}/confirm`, {
    accessToken: token,
    body: { item_id: taxonomyItem.item_id },
  }), 200, "confirmar taxonomía");
  assertTaxonomyAuditEvents(taxonomyDraft.package_id);
  assistantTaxonomyId = taxonomyConfirmed.entity_id;
  const liveTaxonomies = check(await api("GET", "/library/taxonomies", { accessToken: token }), 200, "leer taxonomías vivas");
  const liveTaxonomy = liveTaxonomies.find((entry) => entry.id === assistantTaxonomyId);
  if (!liveTaxonomy || liveTaxonomy.code !== taxonomyCode || liveTaxonomy.name !== taxonomyName) {
    throw new Error("la confirmación no aplicó la taxonomía propuesta");
  }

  const taxonomyUpdateMessage = randomUUID();
  const updatedTaxonomyName = `${taxonomyName} actualizada`;
  await sendSourceMessage(sessionId, taxonomyUpdateMessage,
    `Edita la taxonomía ${assistantTaxonomyId}. Cambia name a ${updatedTaxonomyName} y conserva los demás campos exactamente como están: ${JSON.stringify(liveTaxonomy)}.`);
  const taxonomyUpdateDraft = check(await api("POST", `/agent/sessions/${sessionId}/taxonomy-drafts`, {
    accessToken: token,
    body: { client_message_id: taxonomyUpdateMessage, operation: "update", target_id: assistantTaxonomyId },
  }), 201, "generar edición de taxonomía");
  const taxonomyUpdateItem = taxonomyUpdateDraft.content.items?.[0];
  if (!taxonomyUpdateItem || taxonomyUpdateItem.verification_status !== "PASS"
      || Date.parse(taxonomyUpdateItem.base_version) !== Date.parse(liveTaxonomy.updated_at)
      || taxonomyUpdateItem.diff?.name?.after !== updatedTaxonomyName) {
    throw new Error("edición taxonomía sin diff, verificación o base_version correctos");
  }
  const taxonomyUpdateConfirmed = check(await api("POST", `/agent/sessions/${sessionId}/taxonomy-drafts/${taxonomyUpdateDraft.package_id}/confirm`, {
    accessToken: token,
    body: { item_id: taxonomyUpdateItem.item_id },
  }), 200, "confirmar edición taxonomía");
  assertTaxonomyAuditEvents(taxonomyUpdateDraft.package_id);
  if (taxonomyUpdateConfirmed.entity_id !== assistantTaxonomyId) throw new Error("la edición creó una taxonomía distinta");
  const taxonomyConfirmations = check(await api("GET", `/agent/sessions/${sessionId}/confirmations`, { accessToken: token }), 200, "confirmaciones de taxonomía");
  if (![taxonomyConfirmed.confirmation_id, taxonomyUpdateConfirmed.confirmation_id].every((id) => taxonomyConfirmations.some((item) => item.confirmation_id === id && item.status === "VALID"))) {
    throw new Error("confirmaciones de taxonomía no quedaron persistidas");
  }

  const similarCreateMessage = randomUUID();
  const similarText = `Caso similar asistido ${testId}: el cliente reporta acceso digital no reconocido y cambio de dispositivo.`;
  await sendSourceMessage(sessionId, similarCreateMessage,
    `Crea un caso similar. text exacto: ${similarText} Referencia modus_operandi_library_id exacta ${created.entity_id} y taxonomy_library_id exacta ${taxonomyId}.`);
  const similarDraft = check(await api("POST", `/agent/sessions/${sessionId}/similar-case-drafts`, {
    accessToken: token,
    body: { client_message_id: similarCreateMessage, operation: "create" },
  }), 201, "generar borrador de caso similar");
  const similarItem = similarDraft.content.items?.[0];
  if (!similarItem || similarItem.item_type !== "library_similar_case" || similarItem.verification_status !== "PASS"
      || similarDraft.verifications.some((item) => item.status !== "PASS")) {
    throw new Error(`borrador de caso similar no verificado: ${JSON.stringify(similarDraft.verifications)}`);
  }
  if (!similarItem.diff?.text || !similarItem.field_provenance?.text?.source
      || !similarItem.field_provenance?.modus_operandi_library_id?.source) {
    throw new Error("borrador caso similar no incluye diff y procedencia");
  }
  const similarConfirmed = check(await api("POST", `/agent/sessions/${sessionId}/similar-case-drafts/${similarDraft.package_id}/confirm`, {
    accessToken: token,
    body: { item_id: similarItem.item_id },
  }), 200, "confirmar caso similar");
  similarCaseId = similarConfirmed.entity_id;
  assertSimilarCaseAuditEvents(similarDraft.package_id);
  const liveSimilarCases = check(await api("GET", "/library/similar-cases", { accessToken: token }), 200, "leer casos similares");
  const liveSimilarCase = liveSimilarCases.find((entry) => entry.id === similarCaseId);
  if (!liveSimilarCase || liveSimilarCase.text !== similarText || liveSimilarCase.modus_operandi_library_id !== created.entity_id) {
    throw new Error("la confirmación no aplicó el caso similar y sus referencias");
  }

  const similarUpdateMessage = randomUUID();
  const updatedSimilarText = `${similarText} Se confirmó en la llamada con el titular.`;
  await sendSourceMessage(sessionId, similarUpdateMessage,
    `Edita el caso similar ${similarCaseId}. Cambia únicamente text a: ${updatedSimilarText} Conserva las referencias existentes ${JSON.stringify(liveSimilarCase)}.`);
  const similarUpdateDraft = check(await api("POST", `/agent/sessions/${sessionId}/similar-case-drafts`, {
    accessToken: token,
    body: { client_message_id: similarUpdateMessage, operation: "update", target_id: similarCaseId },
  }), 201, "generar edición de caso similar");
  const similarUpdateItem = similarUpdateDraft.content.items?.[0];
  if (!similarUpdateItem || similarUpdateItem.verification_status !== "PASS"
      || Date.parse(similarUpdateItem.base_version) !== Date.parse(liveSimilarCase.updated_at)
      || similarUpdateItem.diff?.text?.after !== updatedSimilarText) {
    throw new Error("edición del caso similar sin diff, verificaciones o base_version correctos");
  }
  const concurrentText = `${similarText} Se verificó durante una actualización concurrente.`;
  const concurrentUpdate = check(await api("PATCH", `/library/similar-cases/${similarCaseId}`, {
    accessToken: token,
    body: { text: concurrentText },
  }), 200, "simular una edición concurrente");
  const staleConfirmation = await api("POST", `/agent/sessions/${sessionId}/similar-case-drafts/${similarUpdateDraft.package_id}/confirm`, {
    accessToken: token,
    body: { item_id: similarUpdateItem.item_id },
  });
  if (staleConfirmation.status !== 409 || staleConfirmation.payload?.detail?.code !== "DRAFT_STALE") {
    throw new Error(`la edición obsoleta no se bloqueó: HTTP ${staleConfirmation.status}`);
  }

  const finalUpdateMessage = randomUUID();
  await sendSourceMessage(sessionId, finalUpdateMessage,
    `Actualiza el caso similar ${similarCaseId}. Cambia únicamente text a: ${updatedSimilarText} Conserva las referencias existentes ${JSON.stringify(concurrentUpdate)}.`);
  const finalUpdateDraft = check(await api("POST", `/agent/sessions/${sessionId}/similar-case-drafts`, {
    accessToken: token,
    body: { client_message_id: finalUpdateMessage, operation: "update", target_id: similarCaseId },
  }), 201, "generar edición sobre la versión vigente del caso similar");
  const finalUpdateItem = finalUpdateDraft.content.items?.[0];
  if (!finalUpdateItem || finalUpdateItem.verification_status !== "PASS"
      || Date.parse(finalUpdateItem.base_version) !== Date.parse(concurrentUpdate.updated_at)) {
    throw new Error("el borrador renovado no usa la última versión del caso similar");
  }
  const similarUpdateConfirmed = check(await api("POST", `/agent/sessions/${sessionId}/similar-case-drafts/${finalUpdateDraft.package_id}/confirm`, {
    accessToken: token,
    body: { item_id: finalUpdateItem.item_id },
  }), 200, "confirmar edición vigente de caso similar");
  if (similarUpdateConfirmed.entity_id !== similarCaseId) throw new Error("la edición creó otro caso similar");
  assertSimilarCaseAuditEvents(finalUpdateDraft.package_id);
  const confirmedSimilarCases = check(await api("GET", "/library/similar-cases", { accessToken: token }), 200, "verificar caso similar actualizado");
  if (confirmedSimilarCases.find((entry) => entry.id === similarCaseId)?.text !== updatedSimilarText) {
    throw new Error("el nuevo borrador no aplicó el texto confirmado");
  }
  const allConfirmations = check(await api("GET", `/agent/sessions/${sessionId}/confirmations`, { accessToken: token }), 200, "leer confirmaciones H5");
  if (![similarConfirmed.confirmation_id, similarUpdateConfirmed.confirmation_id].every((id) => allConfirmations.some((item) => item.confirmation_id === id && item.status === "VALID"))) {
    throw new Error("confirmaciones de casos similares no quedaron persistidas");
  }

  const watchlistMessage = randomUUID();
  const watchlistName = `Watchlist asistida ${testId}`;
  await sendSourceMessage(sessionId, watchlistMessage, `Crea una blacklist con nombre exacto ${watchlistName} y descripción Lista de prueba de monitoreo. No agregues elementos.`);
  const watchlistDraft = check(await api("POST", `/agent/sessions/${sessionId}/watchlist-drafts`, {
    accessToken: token, body: { client_message_id: watchlistMessage, operation: "create" },
  }), 201, "generar borrador watchlist");
  const watchlistItem = watchlistDraft.content.items?.[0];
  if (!watchlistItem || watchlistItem.item_type !== "library_watchlist" || watchlistItem.verification_status !== "PASS"
      || watchlistDraft.verifications.some((item) => item.status !== "PASS")
      || !watchlistItem.diff?.name || !watchlistItem.field_provenance?.name?.source) {
    throw new Error(`borrador watchlist sin verificaciones, diff o procedencia: ${JSON.stringify(watchlistDraft.verifications)}`);
  }
  const watchlistCreated = check(await api("POST", `/agent/sessions/${sessionId}/watchlist-drafts/${watchlistDraft.package_id}/confirm`, {
    accessToken: token, body: { item_id: watchlistItem.item_id },
  }), 200, "confirmar watchlist");
  watchlistId = watchlistCreated.entity_id;
  assertWatchlistAuditEvents(watchlistDraft.package_id);
  const watchlists = check(await api("GET", "/watchlists", { accessToken: token }), 200, "leer watchlists");
  const liveWatchlist = watchlists.find((entry) => entry.id === watchlistId);
  if (!liveWatchlist || liveWatchlist.name !== watchlistName || liveWatchlist.list_type !== "blacklist") {
    throw new Error("la confirmación no aplicó la watchlist propuesta");
  }

  const watchlistUpdateMessage = randomUUID();
  const updatedWatchlistName = `${watchlistName} actualizada`;
  await sendSourceMessage(sessionId, watchlistUpdateMessage, `Edita la watchlist ${watchlistId}. Cambia name a ${updatedWatchlistName} y conserva descripción y tipo: ${JSON.stringify(liveWatchlist)}.`);
  const watchlistUpdateDraft = check(await api("POST", `/agent/sessions/${sessionId}/watchlist-drafts`, {
    accessToken: token, body: { client_message_id: watchlistUpdateMessage, operation: "update", target_id: watchlistId },
  }), 201, "generar edición watchlist");
  const watchlistUpdateItem = watchlistUpdateDraft.content.items?.[0];
  if (!watchlistUpdateItem || watchlistUpdateItem.verification_status !== "PASS"
      || Date.parse(watchlistUpdateItem.base_version) !== Date.parse(liveWatchlist.updated_at)
      || watchlistUpdateItem.diff?.name?.after !== updatedWatchlistName) {
    throw new Error("edición watchlist sin diff, verificación o base_version correctos");
  }
  const concurrentWatchlist = check(await api("PATCH", `/watchlists/${watchlistId}`, {
    accessToken: token, body: { description: "Cambio concurrente para probar CAS." },
  }), 200, "simular edición concurrente watchlist");
  const staleWatchlistConfirmation = await api("POST", `/agent/sessions/${sessionId}/watchlist-drafts/${watchlistUpdateDraft.package_id}/confirm`, {
    accessToken: token, body: { item_id: watchlistUpdateItem.item_id },
  });
  if (staleWatchlistConfirmation.status !== 409 || staleWatchlistConfirmation.payload?.detail?.code !== "DRAFT_STALE") {
    throw new Error(`la edición obsoleta de watchlist no se bloqueó: HTTP ${staleWatchlistConfirmation.status}`);
  }
  const watchlistFinalMessage = randomUUID();
  await sendSourceMessage(sessionId, watchlistFinalMessage, `Actualiza la watchlist ${watchlistId}; nombre exacto ${updatedWatchlistName}, conserva tipo blacklist y la descripción actual ${concurrentWatchlist.description}.`);
  const watchlistFinalDraft = check(await api("POST", `/agent/sessions/${sessionId}/watchlist-drafts`, {
    accessToken: token, body: { client_message_id: watchlistFinalMessage, operation: "update", target_id: watchlistId },
  }), 201, "regenerar watchlist sobre versión vigente");
  const watchlistFinalItem = watchlistFinalDraft.content.items?.[0];
  if (!watchlistFinalItem || watchlistFinalItem.verification_status !== "PASS"
      || Date.parse(watchlistFinalItem.base_version) !== Date.parse(concurrentWatchlist.updated_at)) {
    throw new Error("el borrador watchlist renovado no usa la versión vigente");
  }
  const watchlistUpdated = check(await api("POST", `/agent/sessions/${sessionId}/watchlist-drafts/${watchlistFinalDraft.package_id}/confirm`, {
    accessToken: token, body: { item_id: watchlistFinalItem.item_id },
  }), 200, "confirmar edición watchlist vigente");
  if (watchlistUpdated.entity_id !== watchlistId) throw new Error("la edición watchlist creó otra entidad");
  assertWatchlistAuditEvents(watchlistFinalDraft.package_id);

  const flagMessage = randomUUID();
  const flagName = `Flag asistido ${testId}`;
  await sendSourceMessage(sessionId, flagMessage, `Crea una red flag con nombre exacto ${flagName}, descripción Indicador de prueba de fraude, evolved_variables canal y dispositivo. Sin vínculos de modus operandi.`);
  const flagDraft = check(await api("POST", `/agent/sessions/${sessionId}/flag-drafts`, {
    accessToken: token, body: { client_message_id: flagMessage, operation: "create" },
  }), 201, "generar borrador flag");
  const flagItem = flagDraft.content.items?.[0];
  if (!flagItem || flagItem.item_type !== "library_flag" || flagItem.verification_status !== "PASS"
      || flagDraft.verifications.some((item) => item.status !== "PASS")
      || !flagItem.diff?.name || !flagItem.field_provenance?.name?.source) {
    throw new Error(`borrador flag sin verificaciones, diff o procedencia: ${JSON.stringify(flagDraft.verifications)}`);
  }
  const flagCreated = check(await api("POST", `/agent/sessions/${sessionId}/flag-drafts/${flagDraft.package_id}/confirm`, {
    accessToken: token, body: { item_id: flagItem.item_id },
  }), 200, "confirmar flag");
  flagId = flagCreated.entity_id;
  assertFlagAuditEvents(flagDraft.package_id);
  const flags = check(await api("GET", "/library/flags", { accessToken: token }), 200, "leer flags");
  const liveFlag = flags.find((entry) => entry.id === flagId);
  if (!liveFlag || liveFlag.name !== flagName || liveFlag.flag_type !== "red") {
    throw new Error("la confirmación no aplicó el flag propuesto");
  }

  const flagUpdateMessage = randomUUID();
  const updatedFlagDescription = `${liveFlag.description} Verificado por E2E.`;
  await sendSourceMessage(sessionId, flagUpdateMessage, `Edita el flag ${flagId}; cambia únicamente description a ${updatedFlagDescription}; conserva todo lo demás ${JSON.stringify(liveFlag)}.`);
  const flagUpdateDraft = check(await api("POST", `/agent/sessions/${sessionId}/flag-drafts`, {
    accessToken: token, body: { client_message_id: flagUpdateMessage, operation: "update", target_id: flagId },
  }), 201, "generar edición flag");
  const flagUpdateItem = flagUpdateDraft.content.items?.[0];
  if (!flagUpdateItem || flagUpdateItem.verification_status !== "PASS"
      || Date.parse(flagUpdateItem.base_version) !== Date.parse(liveFlag.updated_at)
      || flagUpdateItem.diff?.description?.after !== updatedFlagDescription) {
    throw new Error("edición flag sin diff, verificación o base_version correctos");
  }
  const concurrentFlag = check(await api("PATCH", `/library/flags/${flagId}`, {
    accessToken: token, body: { description: "Cambio concurrente E2E." },
  }), 200, "simular edición concurrente flag");
  const staleFlagConfirmation = await api("POST", `/agent/sessions/${sessionId}/flag-drafts/${flagUpdateDraft.package_id}/confirm`, {
    accessToken: token, body: { item_id: flagUpdateItem.item_id },
  });
  if (staleFlagConfirmation.status !== 409 || staleFlagConfirmation.payload?.detail?.code !== "DRAFT_STALE") {
    throw new Error(`la edición obsoleta de flag no se bloqueó: HTTP ${staleFlagConfirmation.status}`);
  }
  const flagFinalMessage = randomUUID();
  await sendSourceMessage(sessionId, flagFinalMessage, `Actualiza el flag ${flagId}; description exacta ${updatedFlagDescription}, conserva tipo red y los demás campos ${JSON.stringify(concurrentFlag)}.`);
  const flagFinalDraft = check(await api("POST", `/agent/sessions/${sessionId}/flag-drafts`, {
    accessToken: token, body: { client_message_id: flagFinalMessage, operation: "update", target_id: flagId },
  }), 201, "regenerar flag sobre versión vigente");
  const flagFinalItem = flagFinalDraft.content.items?.[0];
  if (!flagFinalItem || flagFinalItem.verification_status !== "PASS"
      || Date.parse(flagFinalItem.base_version) !== Date.parse(concurrentFlag.updated_at)) {
    throw new Error("el borrador flag renovado no usa la versión vigente");
  }
  const flagUpdated = check(await api("POST", `/agent/sessions/${sessionId}/flag-drafts/${flagFinalDraft.package_id}/confirm`, {
    accessToken: token, body: { item_id: flagFinalItem.item_id },
  }), 200, "confirmar edición flag vigente");
  if (flagUpdated.entity_id !== flagId) throw new Error("la edición flag creó otra entidad");
  assertFlagAuditEvents(flagFinalDraft.package_id);
  console.log("Agent H5 E2E por nginx: modus operandi, taxonomías, casos similares, watchlists y flags create/update, verificaciones, diff, base_version, confirmación auditada y rechazo concurrente pasaron.");
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
  if (assistantTaxonomyId && token) {
    await api("DELETE", `/library/taxonomies/${assistantTaxonomyId}`, { accessToken: token }).catch(() => undefined);
  }
  if (similarCaseId && token) {
    await api("DELETE", `/library/similar-cases/${similarCaseId}`, { accessToken: token }).catch(() => undefined);
  }
  if (watchlistId && token) {
    await api("DELETE", `/watchlists/${watchlistId}`, { accessToken: token }).catch(() => undefined);
  }
  if (flagId && token) {
    await api("PATCH", `/library/flags/${flagId}`, { accessToken: token, body: { active: false } }).catch(() => undefined);
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
