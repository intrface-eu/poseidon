import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { existsSync, lstatSync, renameSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, expect, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { canonicalJson, parseCommand, parseCommandAck, signingBytes, type Command, type CommandAck, type CommandContext, type HubStateRead } from "../../../libs/proto-ts/src/command-v1";
import type { CalibrationRecord } from "../../../libs/proto-ts/src/calibration-v1";
import type { Credential, Identity } from "../lib/platform";

// Actual built UI + actual API + native AccessGate. No request-context cookie emulation.
const base = process.env.UI_BASE_URL ?? "";
const token = process.env.POSEIDON_ACCESS_TOKEN ?? "";
const artifacts = process.env.PLATFORM_QA_ARTIFACTS ?? "";
const apiBase = process.env.POSEIDON_API_URL ?? "";
if (process.env.PLATFORM_QA_OWNED_WORKSPACE !== "1" || process.env.PLATFORM_QA_TRANCHE3_ONLY !== "1" || !token || !artifacts || !apiBase || new URL(base).hostname !== "127.0.0.1" || new URL(apiBase).hostname !== "127.0.0.1") throw new Error("Tranche 3 QA requires the fresh owned loopback runner and explicit mode");
const prefix = "/api/backend/api/v1";
const apiPrefix = "/api/v1";
const site = "synthetic-tranche3-site";
const zone = "synthetic-tranche3-zone";
const hubId = "synthetic-tranche3-hub";
const proofs: Record<string, unknown>[] = [];
const screenshots: string[] = [];
const errors: string[] = [];
const secrets = new Set([token]);
let step = "native workspace authentication";
let browser: Browser | undefined;
let deadline: ReturnType<typeof setTimeout> | undefined;
let failed: string | null = null;
let browserClosed = false;

function ownedUrl(path: string) {
  const url = new URL(path, base);
  if (url.origin !== new URL(base).origin || url.username || url.password) throw new Error("Request escaped the owned loopback origin");
  return url.href;
}
function ownedApiUrl(path: string) {
  const url = new URL(`${apiPrefix}${path}`, apiBase);
  if (url.origin !== new URL(apiBase).origin || url.username || url.password) throw new Error("Request escaped the owned loopback API origin");
  return url.href;
}
async function request(page: Page, path: string, method = "GET", body?: unknown, raw = false, headers: Record<string, string> = {}) {
  return page.evaluate(async ({ url, method, body, raw, headers }) => {
    const response = await fetch(url, { method, credentials: "same-origin", cache: "no-store", headers: { accept: "application/json", ...(body === undefined ? {} : { "content-type": "application/json" }), ...headers }, ...(body === undefined ? {} : { body: raw ? body as string : JSON.stringify(body) }) });
    return { status: response.status, data: await response.json().catch(() => null) };
  }, { url: ownedUrl(`${prefix}${path}`), method, body, raw, headers });
}
async function api<T>(page: Page, path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await request(page, path, method, body);
  if (response.status < 200 || response.status >= 300) throw new Error(`${method} ${path} HTTP ${response.status}: ${JSON.stringify(response.data)}`);
  return response.data as T;
}
function track(page: Page) { page.on("pageerror", () => errors.push(`pageerror during ${step}`)); }
async function login(context: BrowserContext, credential: string) {
  secrets.add(credential);
  const page = await context.newPage(); track(page);
  await page.goto(ownedUrl("/"), { waitUntil: "domcontentloaded" });
  await page.getByLabel("Local access key", { exact: true }).fill(credential);
  const result = page.waitForResponse((response) => response.url() === ownedUrl("/api/session") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Unlock workspace", exact: true }).click();
  expect((await result).status()).toBe(200);
  await page.getByRole("navigation", { name: "Workbench sections" }).waitFor();
  const cookie = (await context.cookies(base)).find((item) => item.name === "poseidon_session");
  expect(cookie?.httpOnly).toBe(true); expect(cookie?.sameSite).toBe("Strict"); expect(cookie?.value === credential).toBe(true);
  expect(await page.evaluate(() => document.cookie.includes("poseidon_session="))).toBe(false);
  const identity = await api<Identity>(page, "/identity");
  expect(Object.hasOwn(identity, "principal_id")).toBe(false);
  proofs.push({ check: "native browser authentication", role: identity.role, auth_mode: identity.auth_mode, cookie: { httpOnly: true, sameSite: "Strict", javascriptReadable: false }, protectedIdentityStatus: 200, legacyIdentityFieldsPreserved: true });
  return page;
}
async function section(page: Page, name = "Digital operations") {
  await page.getByRole("navigation", { name: "Workbench sections" }).getByRole("button", { name, exact: true }).click();
}
async function details(page: Page, text: string) {
  const summary = page.locator("summary").filter({ hasText: text });
  await expect(summary).toHaveCount(1);
  const element = summary.locator("..");
  if (await element.getAttribute("open") === null) await summary.click();
  return element;
}
async function refresh(page: Page) { await page.getByRole("button", { name: "Refresh digital state", exact: true }).click(); }
async function state(page: Page, value: string) { await expect(page.locator("[data-hub-state]")).toHaveText(value); }
async function shot(page: Page, name: string) {
  if (await page.locator(".one-time-secret").count()) throw new Error("Refusing a screenshot containing a transient credential");
  const body = await page.locator("body").innerText();
  for (const secret of secrets) if (body.includes(secret)) throw new Error("Credential appeared in screenshot text");
  await page.evaluate(() => window.scrollTo(0, 0));
  const path = resolve(artifacts, `platform-tranche3-ui-${name}.png`);
  await page.screenshot({ path, fullPage: true }); screenshots.push(path);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  const domPath = resolve(artifacts, `platform-tranche3-ui-${name}-dom.txt`);
  writeFileSync(domPath, body, { flag: "wx" });
  proofs.push({ check: "DOM and viewport", name, screenshot: path, dom: domPath, noPageOverflow: true });
}
async function submitState(page: Page, kind: string, button: string, expectedState: string, expectedOutcome: CommandAck["outcome"] = "executed") {
  await page.getByRole("button", { name: button, exact: true }).click();
  const submitted = page.waitForResponse((response) => response.url() === ownedUrl(`${prefix}/commands`) && response.request().method() === "POST");
  await page.getByRole("button", { name: `Sign and submit ${kind}`, exact: true }).click();
  const response = await submitted;
  expect(response.status()).toBe(200);
  const ack = parseCommandAck(await response.json());
  expect(ack.outcome).toBe(expectedOutcome); expect(ack.state_after).toBe(expectedState);
  await expect(page.locator(".digital-ack").first()).toContainText(`Actual acknowledgement: ${ack.outcome}`);
  await state(page, expectedState);
  const command = parseCommand(response.request().postData()!);
  expect(typeof command.sequence).toBe("string"); expect(command.device_id).toBe(hubId); expect(command.site_id).toBe(site); expect(command.zone_id).toBe(zone); expect(command.params).toEqual({});
  proofs.push({ check: "native UI signed state command", kind, command_id: command.command_id, sequence: command.sequence, ack, binding: { device_id: command.device_id, site_id: command.site_id, zone_id: command.zone_id }, signing: "browser WebCrypto + shared K1 canonical bytes; server verified" });
  return { ack, command, wire: response.request().postData()! };
}
async function register(admin: Page, id: string, kind = "reef") {
  await api(admin, "/devices", "POST", { id, site_id: site, label: `${id} · synthetic software fixture`, kind, hardware_revision: "simulation-v1", source_kind: "synthetic" });
}
async function profile(admin: Page, id: string) { await api(admin, `/devices/${id}/health-profile`, "PUT", { schema_version: "poseidon.device-health-profile.v1", zone_id: zone, stale_after_s: 300, offline_after_s: 600 }); }
// Telemetry ingest demands a device-role principal bound to that exact device. The same-origin proxy
// replaces Authorization with the session cookie, so device receipts use a direct owned-loopback fetch.
// Device tokens stay in this process memory: never logged, screenshotted or written to an artifact.
const deviceTokens = new Map<string, string>();
async function deviceToken(admin: Page, id: string) {
  const cached = deviceTokens.get(id);
  if (cached) return cached;
  const credential = await issue(admin, `${id}-device`, "device", [site], id);
  deviceTokens.set(id, credential.token);
  return credential.token;
}
async function receipt(admin: Page, id: string, age: number) {
  const bearer = await deviceToken(admin, id);
  const response = await fetch(ownedApiUrl("/telemetry"), { method: "POST", cache: "no-store", headers: { accept: "application/json", "content-type": "application/json", authorization: `Bearer ${bearer}` }, body: JSON.stringify({ schema_version: "poseidon.telemetry.v1", device_id: id, site_id: site, boot_id: "1", sequence: 1, observed_at: null, delivery_age_s: age, clock_quality: { status: "unknown", method: "unknown", uncertainty_ms: null, offset_ms: null, reference: null }, provenance: { source_kind: "synthetic", source_id: "synthetic-browser-fixture", transport: "local" }, measurements: [{ name: "temperature", value: 20, unit: "Cel", quality: "uncalibrated", calibration_id: null }] }) });
  if (!response.ok) throw new Error(`POST /telemetry for ${id} HTTP ${response.status}: ${JSON.stringify(await response.json().catch(() => null))}`);
}
async function issue(admin: Page, subject: string, role: string, sites = [site], deviceId: string | null = null) {
  const result = await api<Credential>(admin, "/principals", "POST", { subject, role, site_ids: sites, device_id: deviceId });
  secrets.add(result.token); return result;
}

const controlPath = resolve(process.env.PLATFORM_QA_WATCHDOG_CONTROL ?? "");
const workspace = resolve(process.env.PLATFORM_QA_WORKSPACE ?? "");
if (!process.env.PLATFORM_QA_WORKSPACE || controlPath !== resolve(workspace, "..", "digital-watchdog-control.json")) throw new Error("Watchdog fixture must be the runner-owned sibling control file, never evidence storage");
function injectFaults(faults: string[]) {
  const info = lstatSync(controlPath);
  if (!info.isFile() || info.isSymbolicLink() || (info.mode & 0o777) !== 0o600 || info.nlink !== 1) throw new Error("Refusing unsafe synthetic fixture control file");
  const temporary = `${controlPath}.next`;
  writeFileSync(temporary, JSON.stringify({ schema_version: "poseidon.digital-watchdog-fixture.v1", live_journal_heartbeat: true, faults }), { mode: 0o600, flag: "wx" });
  renameSync(temporary, controlPath);
}

async function run() {
  const adminContext = await browser!.newContext({ viewport: { width: 1440, height: 1000 } });
  const admin = await login(adminContext, token);
  const healthPulse = await adminContext.newPage();
  await healthPulse.goto(ownedUrl("/api/backend/healthz"));
  await healthPulse.evaluate(() => {
    const counter = { successfulRequests: 0 };
    Object.assign(window, { syntheticQaHealthPulse: counter });
    setInterval(() => { void fetch("/api/backend/healthz", { cache: "no-store", credentials: "same-origin" }).then((response) => { if (response.ok) counter.successfulRequests++; }).catch(() => {}); }, 500);
  });
  await section(admin);
  await expect(admin.getByText("No registered hub binding. No first/default device is used for commands.", { exact: true })).toBeVisible();
  await expect(admin.getByRole("button", { name: "Create and enroll session signing key", exact: true })).toBeDisabled();
  proofs.push({ check: "no default hub or admin operator authority", binding: null, adminSigningDisabled: true });

  step = "actual registry, explicit profile and hub binding";
  await register(admin, hubId, "hub");
  await section(admin, "Devices & telemetry");
  await admin.getByRole("button", { name: "Refresh registry", exact: true }).click();
  await admin.locator(".recording-row").filter({ hasText: hubId }).click();
  const profileForm = await details(admin, "Explicit zone and receipt-health profile");
  await profileForm.getByLabel("Explicit device zone ID", { exact: true }).fill(zone);
  await profileForm.getByLabel("Stale after seconds", { exact: true }).fill("300");
  await profileForm.getByLabel("Offline after seconds", { exact: true }).fill("600");
  await profileForm.getByRole("button", { name: "Enroll explicit health profile", exact: true }).click();
  await expect(profileForm.getByText("Explicit profile enrolled. This does not establish a physical connection.", { exact: true })).toBeVisible();
  await section(admin);
  const binding = await details(admin, "Explicit synthetic hub enrollment");
  await binding.getByLabel("Exact registered synthetic hub ID", { exact: true }).fill(hubId);
  await binding.getByRole("button", { name: "Bind this exact registered hub", exact: true }).click();
  await expect(binding.getByText("API accepted the explicit immutable hub binding. No hardware was connected or enabled.", { exact: true })).toBeVisible();
  await receipt(admin, hubId, 0);
  for (const [health, age] of [["online", 0], ["stale", 350], ["offline", 700], ["revoked", 0], ["unprofiled", null]] as const) {
    const id = `synthetic-tranche3-${health}`;
    await register(admin, id);
    if (health !== "unprofiled") { await profile(admin, id); await receipt(admin, id, age!); }
    if (health === "revoked") await api(admin, `/devices/${id}/revoke`, "POST");
  }
  await refresh(admin);
  for (const health of ["online", "stale", "offline", "revoked", "unprofiled"]) await expect(admin.locator(`[data-device-health="synthetic-tranche3-${health}"]`).locator(".tag")).toHaveText(health);
  proofs.push({ check: "actual age-derived receipt health", source: "synthetic accepted API telemetry with explicit age and profiles", states: ["online", "stale", "offline", "revoked", "unprofiled"], noPhysicalConnectionClaim: true });

  step = "native UI scoped operator enrollment";
  await section(admin, "Identity & access");
  const principalForm = admin.locator("form").filter({ has: admin.getByRole("button", { name: "Issue scoped token", exact: true }) });
  await principalForm.getByLabel("Principal subject", { exact: true }).fill("synthetic-tranche3-operator");
  // The role control is a select wrapped by its label, so its label text also carries every option
  // string; address the form's single combobox by role instead of by exact label text.
  await principalForm.getByRole("combobox").selectOption("operator");
  await principalForm.getByLabel("Authorized site IDs (comma-separated)", { exact: true }).fill(site);
  await principalForm.getByRole("button", { name: "Issue scoped token", exact: true }).click();
  const secret = admin.getByLabel("One-time secret", { exact: true }); await secret.waitFor();
  const operatorToken = await secret.inputValue(); secrets.add(operatorToken);
  await admin.getByRole("button", { name: "I stored the token; clear display", exact: true }).click();
  await expect(secret).toHaveCount(0);
  const operatorContext = await browser!.newContext({ viewport: { width: 1440, height: 1000 } });
  const operator = await login(operatorContext, operatorToken);
  await section(operator);
  await operator.getByRole("button", { name: "Create and enroll session signing key", exact: true }).click();
  await expect(operator.getByText("Session key enrolled. Only its public key went to the API. Reloading, locking or leaving this section drops the private key.", { exact: true })).toBeVisible();
  await expect.poll(async () => (await api<HubStateRead>(operator, "/hub-state")).watchdogs.every((watchdog) => watchdog.healthy), { timeout: 15_000 }).toBe(true);
  await refresh(operator);
  const initial = await api<HubStateRead>(operator, "/hub-state");
  if (initial.state === "inhibited") await submitState(operator, "resume", "Resume to observe", "observe");
  else expect(initial.state).toBe("observe");

  step = "real browser K1 rearm, inhibit, resume and exact duplicate";
  const armed = await submitState(operator, "rearm", "Rearm digital hub", "armed");
  const before = await api<HubStateRead>(operator, "/hub-state");
  const retried = operator.waitForResponse((response) => response.url() === ownedUrl(`${prefix}/commands`) && response.request().method() === "POST");
  await operator.getByRole("button", { name: "Retry exact signed command", exact: true }).click();
  const retryResponse = await retried; const duplicate = parseCommandAck(await retryResponse.json());
  expect(duplicate.outcome).toBe("duplicate"); expect(retryResponse.request().postData()).toBe(armed.wire);
  const after = await api<HubStateRead>(operator, "/hub-state");
  expect(after.last_transitions).toEqual(before.last_transitions);
  await expect(operator.locator(".digital-ack").first()).toContainText("No second execution or transition");
  proofs.push({ check: "exact byte duplicate retry", sameWireBytes: true, noSecondTransition: true, ack: duplicate });
  await submitState(operator, "inhibit", "Inhibit digital hub", "inhibited");
  await submitState(operator, "resume", "Resume to observe", "observe");

  step = "server signature, scope, sequence and digital execution refusals";
  const context = await api<CommandContext>(operator, `/command-context/${hubId}`);
  const pair = generateKeyPairSync("ed25519"); // Synthetic QA key, memory only, never exported private.
  const keyId = "synthetic-tranche3-negative-key";
  const publicHex = pair.publicKey.export({ format: "der", type: "spki" }).subarray(-32).toString("hex");
  await api(operator, "/command-keys", "POST", { key_id: keyId, principal_id: context.principal_id, public_key_hex: publicHex });
  const signPayload = (payload: Record<string, unknown>) => ({ ...payload, signature: { algorithm: "Ed25519", canonicalization: "poseidon-json-v1", value: sign(null, signingBytes(payload, keyId), pair.privateKey).toString("base64") } });
  const command = (kind: string, sequence: string, overrides: Record<string, unknown> = {}) => {
    const now = Date.now();
    return signPayload({ schema_version: "poseidon.command.v1", command_id: crypto.randomUUID(), site_id: site, zone_id: zone, device_id: hubId, principal_id: context.principal_id, key_id: keyId, sequence, issued_at: new Date(now).toISOString(), expires_at: new Date(now + 120_000).toISOString(), kind, params: {}, ...overrides });
  };
  async function outcome(page: Page, doc: unknown, expected: CommandAck["outcome"], name: string, headers: Record<string, string> = {}) {
    const response = await request(page, "/commands", "POST", canonicalJson(doc), true, headers);
    expect(response.status).toBe(200);
    const ack = parseCommandAck(response.data); expect(ack.outcome).toBe(expected);
    proofs.push({ check: name, ack }); return ack;
  }
  await outcome(operator, command("health-request", "9007199254740993"), "executed", "uint64 above IEEE-754 exact integer range");
  const large = await submitState(operator, "inhibit", "Inhibit digital hub", "inhibited");
  expect(large.command.sequence).toBe("9007199254740994");
  await submitState(operator, "resume", "Resume to observe", "observe");
  const invalidSignature = command("inhibit", "9007199254740996"); invalidSignature.signature.value = btoa("\0".repeat(64));
  await outcome(operator, invalidSignature, "rejected", "actual server signature mismatch refusal");
  await outcome(operator, command("inhibit", "1"), "rejected", "non-increasing sequence refusal");
  await outcome(operator, command("inhibit", "9007199254740996"), "rejected", "retained delivery refusal survives UI proxy", { "x-poseidon-retained": "true" });
  await outcome(operator, command("inhibit", "9007199254740996", { device_id: "synthetic-tranche3-unprofiled" }), "rejected", "unprofiled target refusal");
  await outcome(operator, command("inhibit", "9007199254740996", { device_id: "synthetic-tranche3-online" }), "rejected", "registered non-hub cannot change workspace state");
  await outcome(operator, command("resume", "9007199254740996"), "failed", "invalid current digital transition reports failed not executed");
  const expiredNow = Date.now();
  await outcome(operator, command("inhibit", "9007199254740997", { issued_at: new Date(expiredNow - 240_000).toISOString(), expires_at: new Date(expiredNow - 120_000).toISOString() }), "expired", "expired signed command refusal");
  const adminRearm = await request(admin, "/commands", "POST", command("rearm", "9007199254740997"));
  expect(adminRearm.status).toBe(403);
  proofs.push({ check: "admin never implicitly rearms", status: adminRearm.status, acknowledgement: false });
  const forbidden = await request(operator, "/commands", "POST", command("emit", "9007199254740997"));
  expect(forbidden.status >= 400 && forbidden.status < 500).toBe(true);
  proofs.push({ check: "closed enum rejects emit", status: forbidden.status, noEmitEntry: true });

  step = "cross-site and viewer denial through native sessions";
  const foreignCredential = await issue(admin, "synthetic-tranche3-foreign", "operator", ["synthetic-foreign-site"]);
  const foreignContext = await browser!.newContext(); const foreign = await login(foreignContext, foreignCredential.token);
  expect((await request(foreign, "/hub-state")).status).toBe(404);
  expect((await request(foreign, `/command-context/${hubId}`)).status).toBe(404);
  const foreignCommand = await request(foreign, "/commands", "POST", command("rearm", "9007199254740997"));
  expect(foreignCommand.status).toBe(404);
  const viewerCredential = await issue(admin, "synthetic-tranche3-viewer", "viewer");
  const viewerContext = await browser!.newContext(); const viewer = await login(viewerContext, viewerCredential.token);
  await section(viewer); await expect(viewer.getByRole("button", { name: "Rearm digital hub", exact: true })).toBeDisabled();
  expect((await request(viewer, "/command-keys", "POST", { key_id: "synthetic-viewer-key", principal_id: viewerCredential.principal.id, public_key_hex: publicHex })).status).toBe(403);
  proofs.push({ check: "viewer and cross-site controls", viewerRearmDisabled: true, viewerPublicKeyEnrollmentStatus: 403, foreignHubReadStatus: 404, foreignCommandContextStatus: 404, foreignCommandStatus: foreignCommand.status });

  step = "signed digital calibration validity and immutable supersession view";
  const now = Date.now();
  const calibration = (recordId: string, predecessor: string | null, from: number, until: number) => signPayload({ schema_version: "poseidon.calibration-record.v1", record_id: recordId, supersedes_id: predecessor, instrument_id: hubId, quantity: "temperature", unit: "Cel", method: "synthetic-ui-check", reference_id: "synthetic-reference", value: "9007199254740993.123456789", uncertainty: { value: "0.000000001", coverage_factor: "2" }, valid_from: new Date(from).toISOString(), valid_until: new Date(until).toISOString(), operator_id: context.principal_id, source_documents: [createHash("sha256").update("Synthetic digital calibration declaration; not physical calibration").digest("hex")], key_id: keyId, digital_only: true }) as CalibrationRecord;
  await api(operator, "/calibrations", "POST", calibration("synthetic-calibration-predecessor", null, now - 60_000, now + 86_400_000));
  await api(operator, "/calibrations", "POST", calibration("synthetic-calibration-current", "synthetic-calibration-predecessor", now - 30_000, now + 172_800_000));
  await api(operator, "/calibrations", "POST", calibration("synthetic-calibration-future", null, now + 86_400_000, now + 172_800_000));
  await api(operator, "/calibrations", "POST", calibration("synthetic-calibration-expiring", null, Date.now() - 1000, Date.now() + 5000));
  await refresh(operator);
  const currentRecord = await details(operator, "synthetic-calibration-current · current");
  await expect(currentRecord).toContainText("DIGITAL_ONLY=true · Not physical calibration.");
  await expect(currentRecord).toContainText("9007199254740993.123456789");
  await currentRecord.getByRole("button", { name: "Read predecessor synthetic-calibration-predecessor", exact: true }).click();
  await expect(operator.getByRole("region", { name: "Immutable calibration predecessor" })).toContainText("superseded");
  await expect(operator.locator("summary").filter({ hasText: "synthetic-calibration-future · not_yet_valid" })).toBeVisible();
  proofs.push({ check: "actual signed calibration validity", current: "synthetic-calibration-current", predecessor: "synthetic-calibration-predecessor", predecessorValidity: "superseded", futureValidity: "not_yet_valid", exactDecimal: "9007199254740993.123456789", digitalOnly: true, physicalCalibration: false });

  step = "actual backend watchdog fault injections and signed fault recovery";
  for (const [fault, expectedState] of [["hung-heartbeat", "inhibited"], ["network-loss", "inhibited"], ["sensor-disconnect", "inhibited"], ["full-disk", "fault"], ["full-inodes", "fault"], ["clock-regression", "fault"], ["journal-corruption", "fault"], ["unrecoverable-job-failure", "fault"]] as const) {
    step = `backend-owned synthetic watchdog ${fault}`;
    await submitState(operator, "rearm", "Rearm digital hub", "armed");
    injectFaults([fault]);
    await expect.poll(async () => (await api<HubStateRead>(operator, "/hub-state")).state, { timeout: 15_000 }).toBe(expectedState);
    await refresh(operator); await state(operator, expectedState);
    await expect(operator.getByRole("button", { name: "Rearm digital hub", exact: true })).toBeDisabled();
    const faultState = await api<HubStateRead>(operator, "/hub-state");
    expect(faultState.watchdogs.some((watchdog) => !watchdog.healthy)).toBe(true);
    proofs.push({ check: "backend-owned watchdog injection", fault, state: faultState.state, watchdogs: faultState.watchdogs, transition: faultState.last_transitions[0], physicalFaultInjection: false, publicFaultEndpoint: false, directSqlMutation: false });
    if (fault === "full-disk") {
      // The real UI submits clear-fault; the server refuses execution before the alarm ack.
      await submitState(operator, "clear-fault", "Clear acknowledged fault", "fault", "failed");
      await expect(operator.getByRole("button", { name: "Inhibit digital hub", exact: true })).toBeDisabled();
      await shot(operator, "fault-before-ack");
    }
    injectFaults([]);
    await expect.poll(async () => (await api<HubStateRead>(operator, "/hub-state")).watchdogs.every((watchdog) => watchdog.healthy), { timeout: 15_000 }).toBe(true);
    if (expectedState === "fault") {
      const faultAlarms = await api<{ items: { id: string; source: string; severity: string; acknowledged_by: string | null }[] }>(operator, "/alarms?limit=25&offset=0");
      await refresh(operator);
      for (const alarm of faultAlarms.items.filter((item) => item.source === "hub" && !item.acknowledged_by)) {
        const row = operator.locator(`[data-alarm-id="${alarm.id}"]`);
        if (await row.getAttribute("open") === null) await row.locator("summary").click();
        await row.getByRole("button", { name: "Acknowledge alarm", exact: true }).click();
        await expect(row.getByRole("button", { name: "Acknowledge alarm", exact: true })).toBeDisabled();
      }
      await submitState(operator, "clear-fault", "Clear acknowledged fault", "inhibited");
    }
    await submitState(operator, "resume", "Resume to observe", "observe");
  }
  const transitionAudit = await api<HubStateRead>(operator, "/hub-state");
  expect(transitionAudit.last_transitions).toHaveLength(10);
  await refresh(operator);
  await expect(operator.locator("[data-transition-id]")).toHaveCount(10);
  expect(transitionAudit.last_transitions.some((transition) => transition.to_state === "emit")).toBe(false);
  const pulseCount = await healthPulse.evaluate(() => (window as unknown as { syntheticQaHealthPulse: { successfulRequests: number } }).syntheticQaHealthPulse.successfulRequests);
  expect(pulseCount).toBeGreaterThan(0);
  proofs.push({ check: "last-ten audit and real API liveness", transitionCount: 10, transitions: transitionAudit.last_transitions, nativeHealthzRequests: pulseCount, apiLoopPulse: "actual backend event loop", sensorHeartbeat: "explicit synthetic fixture only" });

  step = "alarm acknowledgement, audit, responsive DOM and session-key loss";
  const alarms = await api<{ items: { id: string; acknowledged_by: string | null }[] }>(operator, "/alarms?limit=200&offset=0");
  const unacknowledged = alarms.items.find((alarm) => !alarm.acknowledged_by);
  expect(Boolean(unacknowledged)).toBe(true);
  await refresh(operator);
  const alarmRow = operator.locator(`[data-alarm-id="${unacknowledged!.id}"]`);
  if (await alarmRow.getAttribute("open") === null) await alarmRow.locator("summary").click();
  await alarmRow.getByRole("button", { name: "Acknowledge alarm", exact: true }).click();
  await expect(operator.getByText(new RegExp(`Acknowledged ${unacknowledged!.id} by`))).toBeVisible();
  proofs.push({ check: "native alarm acknowledgement", alarmId: unacknowledged!.id, doesNotClearFault: true });
  await expect.poll(async () => (await api<{ validity: string }>(operator, "/calibrations/synthetic-calibration-expiring")).validity, { timeout: 15_000 }).toBe("expired");
  await refresh(operator);
  await expect(operator.locator("summary").filter({ hasText: "synthetic-calibration-expiring · expired" })).toBeVisible();
  proofs.push({ check: "expired calibration remains visible", record: "synthetic-calibration-expiring", validity: "expired", source: "actual passage of the short synthetic record validity window; no stored-record edits" });
  await shot(operator, "desktop");
  await operator.setViewportSize({ width: 390, height: 844 });
  await shot(operator, "mobile");
  await operator.setViewportSize({ width: 1440, height: 1000 });
  const storage = await operator.evaluate(() => ({ localKeys: Object.keys(localStorage), sessionKeys: Object.keys(sessionStorage) }));
  expect(storage).toEqual({ localKeys: [], sessionKeys: [] });
  await operator.reload({ waitUntil: "domcontentloaded" }); await section(operator);
  await expect(operator.getByRole("button", { name: "Create and enroll session signing key", exact: true })).toBeEnabled();
  await expect(operator.getByRole("button", { name: "Rearm digital hub", exact: true })).toBeDisabled();
  proofs.push({ check: "private key session custody", privateKeyExported: false, browserStorageKeys: storage, signingAuthorityLostOnReload: true, publicRegistrySurvives: true });
  await api(operator, `/command-keys/${keyId}/revoke`, "POST");
  await outcome(operator, command("inhibit", "9007199254740997"), "rejected", "revoked key refusal");
  expect(errors).toEqual([]);
}

try {
  if (existsSync(resolve(artifacts, "platform-tranche3-ui-browser.json"))) throw new Error("Prior browser evidence is immutable");
  browser = await chromium.launch({ headless: true });
  const timeout = new Promise<never>((_resolve, reject) => { deadline = setTimeout(() => reject(new Error(`300-second browser hard deadline at ${step}`)), 300_000); });
  await Promise.race([run(), timeout]);
} catch (caught) {
  failed = caught instanceof Error ? caught.message : "Browser QA failed";
  for (const secret of secrets) failed = failed.split(secret).join("[REDACTED]");
  process.exitCode = 1;
} finally {
  if (deadline) clearTimeout(deadline);
  if (browser) { await browser.close(); browserClosed = !browser.isConnected(); }
  const result = { gate: "platform-tranche3-real-api-built-ui-native-browser-auth", status: failed ? "failed" : "passed", step, error: failed, proofs, screenshots, pageErrors: errors, browserClosed, mockEndpoints: false, syntheticFixturesOnly: true, physicalOrProductionEvidence: false };
  const path = resolve(artifacts, "platform-tranche3-ui-browser.json");
  writeFileSync(`${path}.tmp`, JSON.stringify(result, null, 2) + "\n", { flag: "wx" }); renameSync(`${path}.tmp`, path);
  console.log(JSON.stringify({ gate: result.gate, status: result.status, step, proofCount: proofs.length, screenshots, browserClosed, report: path, error: failed }));
}
