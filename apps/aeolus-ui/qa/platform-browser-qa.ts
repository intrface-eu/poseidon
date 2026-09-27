import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, expect, type Browser, type BrowserContext, type Page, type Locator } from "@playwright/test";
import type { AcousticEvent, ApiPage, EventDetail, Job, Recording, Review, VideoEvidence, Waveform } from "../lib/api-types";
import type { Identity, Observation, Telemetry } from "../lib/platform";

// Run only through the owned-server, hard-timeout runner. Never record traces or secrets.
const base = process.env.UI_BASE_URL ?? "";
const token = process.env.POSEIDON_ACCESS_TOKEN ?? "";
const artifacts = process.env.PLATFORM_QA_ARTIFACTS ?? "";
if (process.env.PLATFORM_QA_OWNED_WORKSPACE !== "1" || !token || !artifacts || !["127.0.0.1", "localhost"].includes(new URL(base).hostname)) throw new Error("QA requires an explicitly owned loopback workspace and temporary credential.");
const prefix = `/api/backend/api/v1`;
const results: string[] = [];
const screenshots: string[] = [];
const errors: string[] = [];
const secrets = new Set<string>([token]);
const authProofs: Record<string, unknown>[] = [];
const legacyProofs: Record<string, unknown>[] = [];
const legacyOnly = process.env.PLATFORM_QA_LEGACY_ONLY === "1";
let currentStep = "owned workspace login";
const id = `synthetic-ui-${Date.now()}`;
const site = `${id}-site`;
const device = `${id}-device`;
let browser: Browser | undefined;
let inspectedPage: Page | undefined;
let deadline: ReturnType<typeof setTimeout> | undefined;

function ownedUrl(value: string): string {
  const origin = new URL(base).origin;
  const url = new URL(value, `${origin}/`);
  if (url.origin !== origin || url.username || url.password) throw new Error("QA request must stay on its owned loopback origin");
  return url.href;
}
async function browserRequest(page: Page, path: string, method = "GET", body?: unknown) {
  const result = await page.evaluate(async ({ url, method, payload, hasBody }) => {
    const response = await fetch(url, {
      method, credentials: "same-origin", cache: "no-store",
      headers: hasBody ? { "content-type": "application/json" } : { accept: "application/json" },
      ...(hasBody ? { body: JSON.stringify(payload) } : {}),
    });
    const data: unknown = await response.json().catch(() => null);
    return { status: response.status, data };
  }, { url: ownedUrl(path), method, payload: body ?? null, hasBody: body !== undefined });
  return { status: () => result.status, ok: () => result.status >= 200 && result.status < 300, json: async () => result.data };
}
async function api<T>(page: Page, path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await browserRequest(page, `${prefix}${path}`, method, body);
  if (!response.ok()) throw new Error(`${method} ${path} returned HTTP ${response.status()}`);
  return response.json() as Promise<T>;
}
async function authenticatePage(page: Page, credential: string): Promise<number> {
  secrets.add(credential); inspectedPage = page;
  await page.bringToFront();
  await page.goto(ownedUrl("/"), { waitUntil: "domcontentloaded" });
  await page.getByLabel("Local access key", { exact: true }).fill(credential);
  const responsePromise = page.waitForResponse((response) => response.url() === ownedUrl("/api/session") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Unlock workspace", exact: true }).click();
  const response = await responsePromise;
  if (response.status() === 200) {
    expect(response.headers()["cache-control"]).toBe("no-store");
    await page.getByRole("navigation", { name: "Workbench sections" }).waitFor();
  } else {
    await expect(page.getByText("Access not granted.", { exact: true })).toBeVisible();
  }
  return response.status();
}
async function sessionStatus(context: BrowserContext, credential: string): Promise<number> {
  // Compatibility helper for older scenarios: every probe gets a fresh browser context.
  const activeBrowser = context.browser();
  if (!activeBrowser) throw new Error("Session probes require a real browser context");
  const isolated = await activeBrowser.newContext({ baseURL: ownedUrl("/") });
  try {
    const page = await isolated.newPage(); track(page);
    return await authenticatePage(page, credential);
  } finally { await isolated.close(); }
}
async function assertCookieContract(page: Page, credential: string, label: string) {
  const cookie = (await page.context().cookies(ownedUrl("/"))).find((item) => item.name === "poseidon_session");
  if (!cookie) throw new Error(`${label}: actual browser session cookie missing`);
  const remainingSeconds = cookie.expires - Date.now() / 1000;
  const attributes = { name: cookie.name, httpOnly: cookie.httpOnly, sameSite: cookie.sameSite, path: cookie.path, domain: cookie.domain, secure: cookie.secure };
  expect(attributes).toEqual({ name: "poseidon_session", httpOnly: true, sameSite: "Strict", path: "/", domain: new URL(base).hostname, secure: new URL(base).protocol === "https:" });
  expect(remainingSeconds > 28700 && remainingSeconds <= 28805).toBe(true);
  expect(cookie.value === credential).toBe(true);
  expect(await page.evaluate(() => document.cookie.includes("poseidon_session="))).toBe(false);
  authProofs.push({ operation: label, cookieAttributes: attributes, cookieLifetimeRemainingSeconds: Math.floor(remainingSeconds), cookieValueMatchesIssuedCredential: true, documentCookieExposesSession: false });
}
async function assertProtectedIdentity(page: Page, expected: Partial<Identity>, label: string) {
  const response = await browserRequest(page, `${prefix}/identity`);
  expect(response.status()).toBe(200);
  const identity = await response.json() as Identity;
  expect(identity).toMatchObject(expected);
  authProofs.push({ operation: label, protectedStatus: 200, identity });
}
async function assertInvalidated(page: Page, label: string) {
  const response = await browserRequest(page, `${prefix}/identity`);
  expect(response.status()).toBe(401);
  expect((await page.context().cookies(ownedUrl("/"))).some((item) => item.name === "poseidon_session")).toBe(false);
  await page.reload({ waitUntil: "domcontentloaded" });
  await expect(page.getByLabel("Local access key", { exact: true })).toBeVisible();
  authProofs.push({ operation: label, previouslyAuthenticatedProtectedStatus: 401, sessionCookieCleared: true, accessGateVisibleAfterReload: true });
}
async function assertRejectedFresh(activeBrowser: Browser, credential: string, label: string) {
  const context = await activeBrowser.newContext({ baseURL: ownedUrl("/") });
  try {
    expect((await context.cookies()).length).toBe(0);
    const page = await context.newPage(); track(page);
    expect(await authenticatePage(page, credential)).toBe(401);
    expect((await browserRequest(page, `${prefix}/identity`)).status()).toBe(401);
    expect((await context.cookies(ownedUrl("/"))).some((item) => item.name === "poseidon_session")).toBe(false);
    authProofs.push({ operation: label, freshContext: true, sessionPostStatus: 401, protectedStatus: 401, sessionCookiePresent: false });
  } finally { await context.close(); }
}

function track(page: Page) {
  inspectedPage = page;
  page.on("pageerror", () => errors.push("browser pageerror"));
  page.on("dialog", (dialog) => { void dialog.accept(); });
}
function formFor(page: Page, buttonName: string): Locator {
  return page.locator("form").filter({ has: page.getByRole("button", { name: buttonName, exact: true }) });
}
async function openDetails(page: Page, summaryText: string): Promise<Locator> {
  await page.bringToFront();
  const summary = page.locator("summary").filter({ hasText: summaryText });
  await expect(summary).toHaveCount(1);
  const details = summary.locator("..");
  if (await details.getAttribute("open") === null) await summary.click();
  return details;
}
function safeError(error: unknown): string {
  let message = error instanceof Error ? error.message : "QA failure";
  for (const secret of secrets) if (secret) message = message.split(secret).join("[REDACTED]");
  return message;
}
async function unlock(page: Page, credential: string) {
  expect(await authenticatePage(page, credential)).toBe(200);
}

async function section(page: Page, name: string) {
  await page.bringToFront();
  await page.getByRole("navigation", { name: "Workbench sections" }).getByRole("button", { name, exact: true }).click();
}
async function shot(page: Page, name: string) {
  if (await page.locator(".one-time-secret").count()) throw new Error("Refusing screenshot while a transient secret panel is present");
  await page.evaluate(() => window.scrollTo(0, 0));
  const path = resolve(artifacts, `${name}.png`);
  await page.screenshot({ path, fullPage: true }); screenshots.push(path);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  if (overflow) throw new Error(`Page-level horizontal overflow at ${name}`);
}
function silence() {
  const bytes = Buffer.alloc(44 + 16000);
  bytes.write("RIFF", 0); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write("WAVEfmt ", 8); bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22); bytes.writeUInt32LE(8000, 24); bytes.writeUInt32LE(16000, 28); bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34); bytes.write("data", 36); bytes.writeUInt32LE(16000, 40);
  return bytes;
}
async function issue(page: Page, subject: string, role: string, deviceId?: string) {
  const form = formFor(page, "Issue scoped token");
  await form.locator("label").filter({ hasText: /^Principal subject/ }).locator("input").fill(subject);
  await form.locator("select").selectOption(role);
  await form.locator("label").filter({ hasText: /^Authorized site IDs/ }).locator("input").fill(site);
  if (deviceId) await form.locator("label").filter({ hasText: /^Registered device ID/ }).locator("input").fill(deviceId);
  await page.getByRole("button", { name: "Issue scoped token", exact: true }).click();
  const secret = page.locator(".one-time-secret input"); await secret.waitFor();
  const value = await secret.inputValue();
  secrets.add(value);
  await page.getByRole("button", { name: "I stored the token; clear display", exact: true }).click();
  await expect(secret).toHaveCount(0);
  if ((await page.content()).includes(value)) throw new Error("Transient credential remained in HTML after dismissal");
  return value;
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
  return JSON.stringify(value);
}

async function setupRemainingFixtures(page: Page) {
  for (const [deviceId, siteId] of [[device, site], [`${id}-other-device`, site], [`${id}-foreign-device`, `${id}-foreign-site`]]) {
    await api(page, "/devices", "POST", { id: deviceId, site_id: siteId, label: "Synthetic remaining-path fixture; not connected", kind: "reef", hardware_revision: "simulation-v1", source_kind: "synthetic" });
  }
  const wav = silence();
  const manifest = { schema_version: 1, recording_id: id, site_id: site, zone_id: `${id}-zone`, device_id: device, started_at: new Date().toISOString(), provenance: "synthetic", wav_sha256: createHash("sha256").update(wav).digest("hex"), calibration_status: "uncalibrated" };
  const imported = await page.request.post(ownedUrl(`${base}${prefix}/recordings`), { headers: { origin: new URL(base).origin }, multipart: { wav: { name: "synthetic-silence.wav", mimeType: "audio/wav", buffer: wav }, manifest: { name: "synthetic-manifest.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(manifest)) } } });
  if (!imported.ok()) throw new Error(`Minimal synthetic import failed with HTTP ${imported.status()}`);
  let job = await imported.json() as Job;
  for (let attempt = 0; attempt < 100 && ["queued", "running"].includes(job.status); attempt++) { await page.waitForTimeout(100); job = await api<Job>(page, `/jobs/${job.id}`); }
  if (job.status !== "succeeded") throw new Error("Minimal synthetic import did not complete");
  await api(page, "/acquisition-sessions", "POST", { schema_version: "poseidon.acquisition-session.v1", id: `${id}-session`, site_id: site, device_id: device, started_at: null, ended_at: null, clock_quality: { status: "unknown", method: "unknown", uncertainty_ms: null, offset_ms: null, reference: null }, provenance: { source_kind: "synthetic", source_id: `${id}-source`, transport: "import" }, operator: "Synthetic fixture operator", notes: "Minimal setup for remaining-path QA only; no field evidence." });
  await api(page, `/recordings/${id}/acquisition-session`, "PUT", { session_id: `${id}-session` });
}

async function runResidual(page: Page, activeBrowser: Browser) {
  currentStep = "real AccessGate session-cookie and protected-identity contract";
  await assertCookieContract(page, token, "development session cookie");
  const adminIdentity = await api<Identity>(page, "/identity");
  await assertProtectedIdentity(page, { subject: adminIdentity.subject, role: "admin", auth_mode: "local_development_key", device_id: null }, "development protected identity");
  results.push("Real AccessGate HTTP 200, actual HttpOnly/Strict/path/domain/Secure/eight-hour cookie contract and protected admin identity");

  currentStep = "minimal synthetic residual credentials";
  await api(page, "/devices", "POST", { id: device, site_id: site, label: "Synthetic residual-revocation fixture; not connected", kind: "reef", hardware_revision: "simulation-v1", source_kind: "synthetic" });
  await section(page, "Identity & access");
  const viewerSubject = `${id}-viewer`;
  const viewerToken = await issue(page, viewerSubject, "viewer");
  const deviceToken = await issue(page, `${id}-principal-device`, "device", device);
  const principals = await api<ApiPage<{ id: string; subject: string }>>(page, "/principals");
  const viewerPrincipal = principals.items.find((item) => item.subject === viewerSubject);
  if (!viewerPrincipal) throw new Error("Synthetic principal fixture missing from scoped registry");
  const oldContext = await activeBrowser.newContext({ baseURL: ownedUrl("/") });
  const replacementContext = await activeBrowser.newContext({ baseURL: ownedUrl("/") });
  const deviceContext = await activeBrowser.newContext({ baseURL: ownedUrl("/") });
  try {
    currentStep = "rotation of an already-authenticated browser session";
    const oldPage = await oldContext.newPage(); track(oldPage);
    await unlock(oldPage, viewerToken);
    await assertCookieContract(oldPage, viewerToken, "original viewer cookie");
    await assertProtectedIdentity(oldPage, { subject: viewerSubject, role: "viewer", site_ids: [site], device_id: null, auth_mode: "scoped_token" }, "original viewer protected identity");
    inspectedPage = page;
    const viewerDetails = await openDetails(page, viewerSubject);
    await viewerDetails.getByRole("button", { name: "Rotate token", exact: true }).click();
    const tokenField = page.locator(".one-time-secret input"); await tokenField.waitFor();
    const replacementToken = await tokenField.inputValue(); secrets.add(replacementToken);
    await page.getByRole("button", { name: "I stored the token; clear display", exact: true }).click();
    await expect(page.locator(".one-time-secret")).toHaveCount(0);
    await assertInvalidated(oldPage, "rotation invalidates original authenticated viewer");
    await assertRejectedFresh(activeBrowser, viewerToken, "rotation rejects original token in a fresh context");
    const replacementPage = await replacementContext.newPage(); track(replacementPage);
    await unlock(replacementPage, replacementToken);
    await assertCookieContract(replacementPage, replacementToken, "replacement viewer cookie");
    await assertProtectedIdentity(replacementPage, { subject: viewerSubject, role: "viewer", site_ids: [site], device_id: null, auth_mode: "scoped_token" }, "replacement viewer protected identity");
    results.push("Rotation invalidates an existing viewer session and fresh old-token login; replacement authenticates with the full cookie contract");

    currentStep = "principal revocation of existing and fresh sessions";
    inspectedPage = page;
    const rotated = await openDetails(page, viewerSubject);
    await rotated.getByRole("button", { name: "Revoke principal", exact: true }).click();
    await expect(page.getByText(`Revoked ${viewerSubject}.`, { exact: true })).toBeVisible();
    await assertInvalidated(replacementPage, "principal revocation invalidates authenticated replacement viewer");
    await assertRejectedFresh(activeBrowser, replacementToken, "principal revocation rejects fresh replacement-token login");
    results.push("Principal revocation denies the already-authenticated replacement session and fresh authentication; cookie clears and AccessGate returns");

    currentStep = "device revocation of existing and fresh sessions";
    const devicePage = await deviceContext.newPage(); track(devicePage);
    await unlock(devicePage, deviceToken);
    await assertCookieContract(devicePage, deviceToken, "device session cookie");
    await assertProtectedIdentity(devicePage, { subject: `${id}-principal-device`, role: "device", site_ids: [site], device_id: device, auth_mode: "scoped_token" }, "device protected identity");
    inspectedPage = page;
    await section(page, "Devices & telemetry");
    await page.locator(".recording-row").filter({ hasText: `${device} · site ${site}` }).click();
    await page.getByRole("button", { name: "Revoke device and its credentials", exact: true }).click();
    await expect(page.getByText("Device revoked. This changed local authorization, not physical hardware.", { exact: true })).toBeVisible();
    await assertInvalidated(devicePage, "device revocation invalidates authenticated device session");
    await assertRejectedFresh(activeBrowser, deviceToken, "device revocation rejects fresh device-token login");
    results.push("Device revocation denies an already-authenticated device and fresh authentication; actual session cookie clears");

    currentStep = "admin audit and expanded matching rotation/revocation records";
    inspectedPage = page;
    await section(page, "Audit trail");
    await expect(page.getByRole("heading", { name: "Security audit trail", exact: true })).toBeVisible();
    const audit = await api<ApiPage<{ action: string; actor_subject: string; auth_mode: string; resource_id: string; created_at: string }>>(page, "/audit");
    for (const [action, resource] of [["principal.rotate", viewerPrincipal.id], ["principal.revoke", viewerPrincipal.id], ["device.revoke", device]]) {
      const row = audit.items.find((entry) => entry.action === action && entry.resource_id === resource);
      if (!row) throw new Error(`Expected relevant audit action missing: ${action}`);
      expect(row.actor_subject).toBe(adminIdentity.subject);
      expect(row.auth_mode).toBe("local_development_key");
      const summary = page.locator("summary").filter({ hasText: `${row.action} · ${row.created_at} · ${row.actor_subject}` });
      await expect(summary).toHaveCount(1);
      const details = summary.locator("..");
      if (await details.getAttribute("open") === null) await summary.click();
      await expect(details.getByRole("heading", { name: "Action detail", exact: true })).toBeVisible();
      await expect(details.locator("pre")).toBeVisible();
      await expect(details).toContainText(resource);
      await expect(details).toContainText(adminIdentity.subject);
      const content = await details.innerText();
      if ([...secrets].some((secret) => content.includes(secret))) throw new Error("Credential found in an audit detail");
      authProofs.push({ operation: "expanded admin audit", action, resource_id: resource, actor_subject: row.actor_subject, auth_mode: row.auth_mode, expandedDetailVisible: true, credentialsAbsent: true });
    }
    results.push("Admin audit expands exact principal.rotate, principal.revoke and device.revoke records with matching actors/resources and no credentials");
  } finally {
    await deviceContext.close(); await replacementContext.close(); await oldContext.close();
  }
}


function silentMp4TrackHandlers(bytes: Buffer): string[] {
  type Box = { type: string; payload: number; end: number };
  function boxes(start: number, end: number): Box[] {
    const found: Box[] = [];
    for (let position = start; position < end;) {
      if (position + 8 > end || found.length >= 128) throw new Error("Invalid bounded synthetic MP4 box layout");
      let size = bytes.readUInt32BE(position);
      let header = 8;
      if (size === 1) {
        if (position + 16 > end) throw new Error("Truncated MP4 extended box");
        const wide = bytes.readBigUInt64BE(position + 8);
        if (wide > BigInt(end - position)) throw new Error("MP4 box exceeds fixture bounds");
        size = Number(wide); header = 16;
      }
      if (size === 0) size = end - position;
      if (size < header || position + size > end) throw new Error("MP4 box exceeds fixture bounds");
      found.push({ type: bytes.toString("ascii", position + 4, position + 8), payload: position + header, end: position + size });
      position += size;
    }
    return found;
  }
  const movie = boxes(0, bytes.length).find((box) => box.type === "moov");
  if (!movie) throw new Error("Synthetic MP4 movie box missing");
  return boxes(movie.payload, movie.end).filter((box) => box.type === "trak").map((track) => {
    const media = boxes(track.payload, track.end).find((box) => box.type === "mdia");
    const handler = media && boxes(media.payload, media.end).find((box) => box.type === "hdlr");
    if (!handler || handler.payload + 12 > handler.end) throw new Error("Synthetic MP4 track handler missing");
    return bytes.toString("ascii", handler.payload + 8, handler.payload + 12);
  });
}

async function legacyMediaBytes(page: Page, path: string, range?: string) {
  return page.evaluate(async ({ url, range }) => {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", headers: range ? { range } : {} });
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length > 2 * 1024 * 1024) throw new Error("Legacy synthetic media response exceeded fixture budget");
    return { status: response.status, bytes: Array.from(bytes), contentType: response.headers.get("content-type"), contentRange: response.headers.get("content-range"), contentLength: response.headers.get("content-length"), acceptRanges: response.headers.get("accept-ranges"), cacheControl: response.headers.get("cache-control") };
  }, { url: ownedUrl(path), range });
}

async function legacySeek(video: Locator, target: number) {
  return video.evaluate((element, desired) => {
    const media = element as HTMLVideoElement;
    media.muted = true; media.volume = 0; media.pause();
    return new Promise<{ currentTime: number; duration: number; muted: boolean; volume: number }>((resolve, reject) => {
      const timer = setTimeout(() => { cleanup(); reject(new Error("Synthetic video seek timed out")); }, 10000);
      const cleanup = () => { clearTimeout(timer); media.removeEventListener("seeked", done); media.removeEventListener("error", failed); };
      const done = () => { cleanup(); resolve({ currentTime: media.currentTime, duration: media.duration, muted: media.muted, volume: media.volume }); };
      const failed = () => { cleanup(); reject(new Error("Synthetic video reported a decoder error during seek")); };
      media.addEventListener("seeked", done, { once: true }); media.addEventListener("error", failed, { once: true });
      media.currentTime = desired;
    });
  }, target);
}

async function runLegacy(page: Page, identity: Identity) {
  currentStep = "legacy fixture provenance and silent-track validation";
  const fixtureRoot = resolve(import.meta.dir, "../../nereid/fixtures/recorded-codec-wave2/input");
  const videoPath = resolve(fixtureRoot, "synthetic.mp4");
  const recipe = await Bun.file(resolve(fixtureRoot, "synthetic-recipe.codec-v1.json")).json();
  const declaration = await Bun.file(resolve(fixtureRoot, "declaration.codec-v1.json")).json();
  const file = Bun.file(videoPath);
  if (!(await file.exists()) || file.size === 0 || file.size > 2 * 1024 * 1024) throw new Error("Approved synthetic legacy MP4 is missing or outside its test budget");
  const videoBytes = Buffer.from(await file.arrayBuffer());
  const videoHash = createHash("sha256").update(videoBytes).digest("hex");
  expect(recipe.provenance).toBe("synthetic"); expect(recipe.software_only).toBe(true);
  expect(declaration.provenance).toBe("synthetic"); expect(declaration.origin).toMatch(/^SYNTHETIC/);
  expect(videoHash).toBe(recipe.source_sha256); expect(videoHash).toBe(declaration.source_sha256);
  const handlers = silentMp4TrackHandlers(videoBytes); expect(handlers).toEqual(["vide"]);
  legacyProofs.push({ operation: "fixture", path: videoPath, sha256: videoHash, bytes: videoBytes.length, provenance: "synthetic", trackHandlers: handlers, silentVideoOnly: true, generator: "Existing recorded-codec-wave2 software libx264 luma fixture; no generation/capture/output in this run" });

  currentStep = "legacy synthetic demo candidate processing and selection";
  await section(page, "Evidence review");
  const submitted = page.waitForResponse((response) => response.url() === ownedUrl(`${prefix}/demo`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "Load synthetic demo", exact: true }).click();
  const submittedResponse = await submitted; expect(submittedResponse.status()).toBe(202);
  let job = await submittedResponse.json() as Job;
  for (let attempt = 0; attempt < 150 && ["queued", "running"].includes(job.status); attempt++) { await page.waitForTimeout(100); job = await api<Job>(page, `/jobs/${job.id}`); }
  expect(job.status).toBe("succeeded");
  await expect(page.getByTitle(job.id).locator("..").locator(".job-state")).toHaveText("succeeded", { timeout: 15000 });
  const recordingId = job.recording_id;
  const candidates = await api<ApiPage<AcousticEvent>>(page, `/events?recording_id=${encodeURIComponent(recordingId)}&limit=200&offset=0`);
  expect(candidates.total).toBeGreaterThan(0);
  const candidate = candidates.items[0];
  expect(candidate).toMatchObject({ event_type: "acoustic_candidate", source: "replay", provenance: "synthetic", calibration_status: "uncalibrated", amplitude_units: "normalized_pcm16_full_scale", emission_enabled: false });
  const eventId = candidate.event_id;
  const eventPath = `/events/${encodeURIComponent(eventId)}`;
  const reviewUrl = ownedUrl(`${prefix}${eventPath}/review`);
  async function selectEvidence() {
    await page.locator(`.recording-rail [title="${recordingId}"]`).locator("..").click();
    const row = page.locator(".event-row").filter({ has: page.locator(`[title="${eventId}"]`) });
    await row.click(); await expect(row).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator(".evidence-inspector .event-identifier")).toHaveText(eventId);
    await expect(page.locator(".evidence-inspector")).not.toHaveClass(/refreshing/);
  }
  await selectEvidence();
  const inspector = page.locator(".evidence-inspector");
  await expect(inspector.locator(".identifier-ledger")).toContainText(recordingId);
  await expect(inspector.locator(".identifier-ledger")).toContainText(candidate.run_id);
  await expect(inspector.locator(".inspector-heading .tag")).toHaveText("synthetic");
  await expect(page.locator(".identity-strip")).toContainText(identity.subject);
  results.push("Legacy demo creates real synthetic candidates; recording/event selection preserves exact IDs, provenance and monitor-only limits");
  legacyProofs.push({ operation: "candidate", jobId: job.id, terminalStatus: job.status, recordingId, eventId, runId: candidate.run_id, candidateCount: candidates.total, source: candidate.source, provenance: candidate.provenance });

  currentStep = "legacy source waveform and exact accessible table";
  const waveform = await api<Waveform>(page, `/recordings/${encodeURIComponent(recordingId)}/waveform?points=512`);
  expect(waveform.recording_id).toBe(recordingId); expect(waveform.buckets.length).toBeGreaterThan(0);
  await expect(inspector.locator(".waveform-chart")).toBeVisible();
  await expect(inspector.locator(".envelope-mark")).toHaveAttribute("d", /.+/);
  await expect(inspector.locator(".event-label")).toHaveText("Candidate interval");
  await expect(inspector.locator(".waveform-figure")).toContainText("normalized PCM16 full-scale · not SPL");
  const tableSummary = inspector.locator("summary").filter({ hasText: `Accessible waveform data table (${waveform.buckets.length} buckets)` });
  await tableSummary.click();
  const tableRows = inspector.locator(".waveform-figure tbody tr");
  await expect(tableRows).toHaveCount(waveform.buckets.length);
  for (const index of [0, waveform.buckets.length - 1]) {
    const bucket = waveform.buckets[index];
    expect(await tableRows.nth(index).locator("th,td").allTextContents()).toEqual([String(index + 1), bucket.start_s.toFixed(6), bucket.end_s.toFixed(6), bucket.min.toFixed(6), bucket.max.toFixed(6)]);
  }
  await tableSummary.click();
  await inspector.locator(".waveform-chart").press("ArrowRight");
  await expect(inspector.locator(".chart-tooltip")).toBeVisible();
  results.push("Legacy candidate waveform renders source-derived buckets, candidate highlight, keyboard inspection and exact accessible table values");
  legacyProofs.push({ operation: "waveform", recordingId, bucketCount: waveform.buckets.length, units: waveform.amplitude_units, calibration: waveform.calibration_status, exactFirstAndLastRows: true });

  currentStep = "legacy candidate review save, actor audit and reload persistence";
  const label = inspector.getByLabel("Observation label", { exact: true });
  const reviewer = inspector.getByLabel("Reviewer", { exact: true });
  const notes = inspector.locator(".review-form textarea");
  const initialNotes = "Synthetic candidate-review regression only; no biological claim.";
  await label.selectOption("uncertain"); await reviewer.fill("Synthetic legacy reviewer"); await notes.fill(initialNotes);
  const saveResponsePromise = page.waitForResponse((response) => response.url() === reviewUrl && response.request().method() === "PUT");
  await inspector.getByRole("button", { name: "Save review", exact: true }).click();
  const saveResponse = await saveResponsePromise; expect(saveResponse.status()).toBe(200);
  const firstReview = await saveResponse.json() as Review;
  expect(firstReview).toMatchObject({ revision: 1, reviewer: "Synthetic legacy reviewer", label: "uncertain", notes: initialNotes });
  await expect(inspector.locator(".review-block .revision-stamp")).toHaveText("revision 1");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("navigation", { name: "Workbench sections" }).waitFor();
  await selectEvidence();
  const persisted = await api<EventDetail>(page, eventPath);
  expect(persisted.event.review).toEqual(firstReview);
  await expect(reviewer).toHaveValue(firstReview.reviewer); await expect(notes).toHaveValue(firstReview.notes); await expect(label).toHaveValue(firstReview.label);
  results.push("Legacy candidate review saves revision 1 and survives real page reload/reselection and API refetch; declared reviewer remains separate from authenticated actor");

  currentStep = "legacy repeated candidate-review 409 draft preservation and explicit resolution";
  const draftNotes = "Synthetic preserved candidate-review draft; distinct from independent intervals.";
  const draftReviewer = "Synthetic preserved reviewer";
  await label.selectOption("non_feeding"); await reviewer.fill(draftReviewer); await notes.fill(draftNotes);
  const second = await api<Review>(page, `${eventPath}/review`, "PUT", { expected_revision: 1, label: "uncertain", reviewer: "Synthetic concurrent reviewer A", notes: "Synthetic concurrent server revision two." });
  expect(second.revision).toBe(2);
  let conflictResponse = page.waitForResponse((response) => response.url() === reviewUrl && response.request().method() === "PUT");
  await inspector.getByRole("button", { name: "Save review", exact: true }).click();
  expect((await conflictResponse).status()).toBe(409);
  const serverVersion = inspector.locator('[aria-labelledby="server-review-title"]');
  const draftVersion = inspector.locator('[aria-labelledby="preserved-draft-title"]');
  await expect(inspector.getByText("Revision conflict.", { exact: true })).toBeVisible();
  await expect(serverVersion).toContainText(second.notes); await expect(serverVersion).toContainText(second.reviewer); await expect(serverVersion).toContainText(second.updated_at);
  await expect(draftVersion).toContainText(draftNotes); await expect(draftVersion).toContainText(draftReviewer);
  await expect(notes).toHaveValue(draftNotes); await expect(reviewer).toHaveValue(draftReviewer); await expect(label).toHaveValue("non_feeding");
  await shot(page, "legacy-candidate-review-conflict");
  const third = await api<Review>(page, `${eventPath}/review`, "PUT", { expected_revision: 2, label: "uncertain", reviewer: "Synthetic concurrent reviewer B", notes: "Synthetic concurrent server revision three." });
  expect(third.revision).toBe(3);
  conflictResponse = page.waitForResponse((response) => response.url() === reviewUrl && response.request().method() === "PUT");
  await inspector.getByRole("button", { name: "Save my draft over revision 2", exact: true }).click();
  expect((await conflictResponse).status()).toBe(409);
  await expect(serverVersion).toContainText(third.notes); await expect(serverVersion).toContainText(third.updated_at);
  await expect(notes).toHaveValue(draftNotes); await expect(draftVersion).toContainText(draftNotes);
  const resolvedResponse = page.waitForResponse((response) => response.url() === reviewUrl && response.request().method() === "PUT");
  await inspector.getByRole("button", { name: "Save my draft over revision 3", exact: true }).click();
  const resolved = await resolvedResponse; expect(resolved.status()).toBe(200);
  const finalReview = await resolved.json() as Review;
  expect(finalReview).toMatchObject({ revision: 4, label: "non_feeding", notes: draftNotes, reviewer: draftReviewer });
  await expect(inspector.locator(".review-block .revision-stamp")).toHaveText("revision 4");
  await expect(inspector.locator(".conflict-comparison")).toHaveCount(0);
  await page.reload({ waitUntil: "domcontentloaded" }); await page.getByRole("navigation", { name: "Workbench sections" }).waitFor(); await selectEvidence();
  expect((await api<EventDetail>(page, eventPath)).event.review).toEqual(finalReview);
  await expect(notes).toHaveValue(draftNotes); await expect(label).toHaveValue("non_feeding");
  const audit = await api<ApiPage<{ action: string; resource_id: string; actor_subject: string; auth_mode: string; details: { event_id?: string; revision?: number } }>>(page, "/audit?limit=200&offset=0");
  const reviewAudit = audit.items.filter((row) => row.action === "review.save" && row.resource_id === recordingId && row.details.event_id === eventId);
  expect(reviewAudit.map((row) => row.details.revision).sort((a, b) => Number(a) - Number(b))).toEqual([1, 2, 3, 4]);
  for (const row of reviewAudit) { expect(row.actor_subject).toBe(identity.subject); expect(row.auth_mode).toBe(identity.auth_mode); }
  results.push("Legacy candidate-review 409s preserve the draft twice; explicit overwrite saves revision 4 with exact actor-stamped revision audit and reload persistence");
  legacyProofs.push({ operation: "candidate review", eventId, recordingId, reviewRevisions: [1, 2, 3, 4], expectedConflictStatuses: [409, 409], finalReview, authenticatedActor: identity.subject, authMode: identity.auth_mode, actorEvidence: "transactional review.save audit; reviewer is declared text", persistence: "page reload/reselection and API refetch; no process restart" });

  currentStep = "legacy synthetic MP4 UI attachment and declared-offset metadata";
  const offset = 0.125;
  await inspector.locator('.video-upload input[name="video"]').setInputFiles({ name: "synthetic-recorded-codec-wave2.mp4", mimeType: "video/mp4", buffer: videoBytes });
  await inspector.locator('.video-upload input[name="offset_s"]').fill(String(offset));
  const mediaPath = `${prefix}/recordings/${encodeURIComponent(recordingId)}/video`;
  const attachmentResponse = page.waitForResponse((response) => response.url() === ownedUrl(mediaPath) && response.request().method() === "POST");
  await inspector.getByRole("button", { name: "Attach video evidence", exact: true }).click();
  const attached = await attachmentResponse; expect(attached.status()).toBe(201);
  const metadata = await attached.json() as VideoEvidence;
  expect(metadata).toMatchObject({ sha256: videoHash, offset_s: offset, alignment: "operator_declared" });
  await expect(inspector.locator(".video-block")).toContainText("Unverified · operator declared");
  await expect(inspector.locator(".video-block")).toContainText("+0.125 s");
  await expect(inspector.locator(".video-block")).toContainText(videoHash);
  await expect(inspector.locator(".video-block")).toContainText("It does not verify synchronization.");
  expect((await api<EventDetail>(page, eventPath)).recording.video).toEqual(metadata);
  results.push("Legacy MP4 attachment uses real UI multipart upload, exact synthetic source hash and unverified operator-declared offset labels");

  currentStep = "legacy muted decoding, playback and bounded seek";
  const video = inspector.locator(".video-evidence video");
  await expect(video).toBeVisible();
  await video.evaluate((element) => { const media = element as HTMLVideoElement; media.muted = true; media.volume = 0; media.pause(); });
  await page.waitForFunction(() => { const media = document.querySelector<HTMLVideoElement>(".video-evidence video"); return Boolean(media && !media.error && media.readyState >= 1 && Number.isFinite(media.duration) && media.duration > 0 && media.videoWidth > 0 && media.videoHeight > 0); }, undefined, { timeout: 15000 });
  const mediaInfo = await video.evaluate((element) => { const media = element as HTMLVideoElement; return { duration: media.duration, width: media.videoWidth, height: media.videoHeight, seekable: Array.from({ length: media.seekable.length }, (_, index) => ({ start: media.seekable.start(index), end: media.seekable.end(index) })) }; });
  expect(mediaInfo.width).toBe(recipe.width); expect(mediaInfo.height).toBe(recipe.height);
  const start = mediaInfo.seekable.length ? mediaInfo.seekable[0].start : 0;
  const end = Math.min(mediaInfo.duration, mediaInfo.seekable.length ? mediaInfo.seekable[mediaInfo.seekable.length - 1].end : mediaInfo.duration);
  const span = end - start; expect(span).toBeGreaterThan(0);
  const playFrom = end - Math.min(0.15, span / 2);
  const firstSeek = await legacySeek(video, playFrom);
  expect(firstSeek.currentTime >= 0 && firstSeek.currentTime < mediaInfo.duration).toBe(true);
  await video.evaluate(async (element) => { const media = element as HTMLVideoElement; media.muted = true; media.volume = 0; await media.play(); });
  await page.waitForFunction(({ initial, advance }) => { const media = document.querySelector<HTMLVideoElement>(".video-evidence video"); return Boolean(media && !media.error && media.currentTime > initial + advance); }, { initial: firstSeek.currentTime, advance: Math.min(0.02, span / 10) }, { timeout: 10000 });
  const played = await video.evaluate((element) => { const media = element as HTMLVideoElement; media.pause(); return { currentTime: media.currentTime, muted: media.muted, volume: media.volume, paused: media.paused, decodedFrames: media.getVideoPlaybackQuality().totalVideoFrames, error: media.error?.code ?? null }; });
  expect(played).toMatchObject({ muted: true, volume: 0, paused: true, error: null }); expect(played.decodedFrames).toBeGreaterThan(0);
  const seekTarget = end - Math.min(0.04, span / 10);
  const seeked = await legacySeek(video, seekTarget);
  expect(Math.abs(seeked.currentTime - seekTarget)).toBeLessThan(0.06);
  expect(seeked.currentTime >= start && seeked.currentTime < mediaInfo.duration).toBe(true);
  expect(seeked.muted).toBe(true); expect(seeked.volume).toBe(0);
  await expect(inspector.getByText("Browser decoder could not open this MP4.", { exact: true })).toHaveCount(0);
  await shot(page, "legacy-synthetic-video-attached");
  results.push("Legacy silent synthetic H.264 loads real metadata, decodes muted frames, advances playback and seeks within the browser's valid media duration");
  legacyProofs.push({ operation: "video playback", fixtureSha256: videoHash, metadata, mediaInfo, playFrom, played, seekTarget, seeked, soundOutput: "None: video-only source, muted=true and volume=0" });

  currentStep = "legacy authenticated media bytes and Range integrity";
  const whole = await legacyMediaBytes(page, mediaPath);
  expect(whole.status).toBe(200); expect(whole.contentType).toMatch(/^video\/mp4/); expect(whole.cacheControl).toBe("no-store");
  expect(Buffer.from(whole.bytes).equals(videoBytes)).toBe(true);
  const ranges: Record<string, unknown>[] = [];
  for (const [from, to] of [[0, 31], [48, 79]]) {
    const range = await legacyMediaBytes(page, mediaPath, `bytes=${from}-${to}`);
    expect(range.status).toBe(206); expect(range.contentRange).toBe(`bytes ${from}-${to}/${videoBytes.length}`); expect(range.contentLength).toBe(String(to - from + 1)); expect(range.acceptRanges).toBe("bytes");
    expect(Buffer.from(range.bytes).equals(videoBytes.subarray(from, to + 1))).toBe(true);
    ranges.push({ from, to, status: range.status, contentRange: range.contentRange, length: range.bytes.length, exactBytes: true });
  }
  results.push("Legacy authenticated full media and two byte ranges return exact stored synthetic bytes with correct 200/206 headers");

  currentStep = "legacy logout denies subsequent whole and Range media requests";
  await video.evaluate((element) => { const media = element as HTMLVideoElement; media.muted = true; media.volume = 0; media.pause(); });
  const logoutResponse = page.waitForResponse((response) => response.url() === ownedUrl("/api/session") && response.request().method() === "DELETE");
  await page.getByRole("button", { name: "Lock workspace", exact: true }).click();
  expect((await logoutResponse).status()).toBe(200);
  await expect(page.getByLabel("Local access key", { exact: true })).toBeVisible();
  expect((await page.context().cookies(ownedUrl("/"))).some((cookie) => cookie.name === "poseidon_session")).toBe(false);
  const deniedWhole = await legacyMediaBytes(page, mediaPath);
  const deniedRange = await legacyMediaBytes(page, mediaPath, "bytes=0-31");
  expect(deniedWhole.status).toBe(401); expect(deniedRange.status).toBe(401);
  expect(deniedWhole.contentType).not.toMatch(/^video\/mp4/); expect(deniedRange.contentRange).toBeNull();
  expect((await browserRequest(page, `${prefix}${eventPath}`)).status()).toBe(401);
  results.push("Legacy logout clears the actual cookie and denies new full/Range video and candidate-detail requests with HTTP 401");
  legacyProofs.push({ operation: "authenticated media integrity", fixtureSha256: videoHash, fullStatus: whole.status, fullBytes: whole.bytes.length, fullExactBytes: true, ranges, logoutStatus: 200, deniedWholeStatus: deniedWhole.status, deniedRangeStatus: deniedRange.status, cookieRemoved: true, boundary: "New authenticated requests are denied; already buffered client bytes are not remotely erased" });
}

async function run() {
  mkdirSync(artifacts, { recursive: true });
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  track(page);
  await unlock(page, token);
  const identity = await api<Identity>(page, "/identity");
  expect(identity.auth_mode).toBe("local_development_key");
  if (legacyOnly) {
    await runLegacy(page, identity);
    expect(errors).toEqual([]);
    return;
  }
  if (process.env.PLATFORM_QA_RESIDUAL_ONLY === "1") {
    await runResidual(page, browser);
    expect(errors).toEqual([]);
    return;
  }
  if (process.env.PLATFORM_QA_REMAINING_ONLY === "1") {
    currentStep = "minimal synthetic fixture setup";
    await setupRemainingFixtures(page);
  } else {
  await section(page, "Devices & telemetry");
  await expect(page.getByText("No registered devices. Nothing is connected by default.", { exact: true })).toBeVisible();
  results.push("Fresh registry is empty; no invented fleet");

  await section(page, "Evidence review");
  const wav = silence();
  const manifest = { schema_version: 1, recording_id: id, site_id: site, zone_id: `${id}-zone`, device_id: device, started_at: new Date().toISOString(), provenance: "synthetic", wav_sha256: createHash("sha256").update(wav).digest("hex"), calibration_status: "uncalibrated" };
  if (!(await page.getByLabel("WAV recording", { exact: true }).isVisible())) await page.getByRole("button", { name: "Import WAV + manifest", exact: true }).click();
  await page.getByLabel("WAV recording", { exact: true }).setInputFiles({ name: "synthetic-silence.wav", mimeType: "audio/wav", buffer: wav });
  await page.getByLabel("Recording manifest", { exact: true }).setInputFiles({ name: "synthetic-silence-manifest.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(manifest)) });
  const submission = page.waitForResponse((response) => response.url().endsWith(`${prefix}/recordings`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "Submit recording", exact: true }).click();
  const response = await submission; expect(response.status()).toBe(202);
  let job = await response.json() as Job;
  for (let attempt = 0; attempt < 100 && ["queued", "running"].includes(job.status); attempt++) { await page.waitForTimeout(100); job = await api<Job>(page, `/jobs/${job.id}`); }
  expect(job.status).toBe("succeeded");
  const recording = await api<Recording>(page, `/recordings/${id}`); expect(recording.event_count).toBe(0);
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await section(page, "Observation intervals");
  await page.locator(".recording-rail .recording-row").filter({ hasText: id }).click();
  await expect(page.getByRole("heading", { name: "Independent observation intervals", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "New observation", exact: true }).click();
  await page.getByLabel("Start (seconds)", { exact: true }).fill("0.1"); await page.getByLabel("End (seconds)", { exact: true }).fill("0.8");
  await page.getByLabel("Declared observer", { exact: true }).fill("Synthetic declared observer");
  await page.getByLabel("Observation notes", { exact: true }).fill("Synthetic zero-candidate coverage; no biological evidence.");
  await page.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect(page.getByText("Observation saved at revision 1.", { exact: true })).toBeVisible();
  let observations = await api<ApiPage<Observation>>(page, `/recordings/${id}/observations`);
  const observation = observations.items[0]; expect(observation.actor_subject).toBe(identity.subject); expect(observation.provenance.recording_sha256).toBe(manifest.wav_sha256);
  results.push("Real synthetic WAV import, zero-candidate interval save and exact source/actor provenance");

  await page.getByLabel("Observation notes", { exact: true }).fill("Synthetic draft preserved across stale revision.");
  await api(page, `/recordings/${id}/observations/${observation.id}`, "PUT", { id: observation.id, start_s: 0.2, end_s: 0.9, label: "not_visible", notes: "Synthetic concurrent server revision.", observer: "Synthetic second declared observer", expected_revision: 1 });
  await page.getByRole("button", { name: "Save observation", exact: true }).click();
  await expect(page.getByText("Revision conflict. Draft preserved.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Observation notes", { exact: true })).toHaveValue("Synthetic draft preserved across stale revision.");
  await expect(page.getByRole("button", { name: "Save my draft over revision 2", exact: true })).toBeVisible();
  await shot(page, "desktop-observation-conflict");
  await page.getByRole("button", { name: "Save my draft over revision 2", exact: true }).click();
  await expect(page.getByText("Observation saved at revision 3.", { exact: true })).toBeVisible();
  observations = await api<ApiPage<Observation>>(page, `/recordings/${id}/observations/${observation.id}/history`); expect(observations.items.map((row) => row.revision)).toEqual([1, 2, 3]);
  results.push("409 keeps draft; explicit resolution appends revision; ascending history retained");

  await section(page, "Devices & telemetry");
  await page.getByText("Register a synthetic or bench device", { exact: true }).click();
  await page.getByLabel("Device ID", { exact: true }).fill(device); await page.getByLabel("Device site ID", { exact: true }).fill(site); await page.getByLabel("Device label", { exact: true }).fill("Synthetic browser-test device; not connected"); await page.getByLabel("Hardware revision", { exact: true }).fill("simulation-v1");
  await page.getByRole("button", { name: "Register local test device", exact: true }).click();
  await expect(page.getByText(`Registered ${device}. Registration does not establish a connection.`, { exact: true })).toBeVisible();
  await page.getByText("AQUILON identity and calibration mapping", { exact: true }).click();
  await page.getByLabel("DevEUI (16 lowercase hex digits)", { exact: true }).fill("0011223344556677");
  await page.getByRole("button", { name: "Store immutable mapping", exact: true }).click();
  await expect(page.getByText("Mapping is immutable. No replacement action is available.", { exact: true })).toBeVisible();
  results.push("Synthetic device registry and immutable AQUILON mapping through UI");

  await section(page, "Acquisition sessions");
  await page.getByText("Declare an acquisition session", { exact: true }).click();
  await page.getByLabel("Session ID", { exact: true }).fill(`${id}-session`); await page.getByLabel("Session site ID", { exact: true }).fill(site); await page.getByLabel("Session device ID (optional)", { exact: true }).fill(device); await page.getByLabel("Exact source ID", { exact: true }).fill(`${id}-source`); await page.getByLabel("Declared session operator", { exact: true }).fill("Synthetic capture operator"); await page.getByLabel("Session notes", { exact: true }).fill("Synthetic source association; no live capture or verified UTC.");
  await page.getByRole("button", { name: "Store declared session", exact: true }).click();
  await expect(page.getByRole("button", { name: "Bind selected session once", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Bind selected session once", exact: true }).click();
  await expect(page.getByText("Acquisition session bound. The original manifest was not changed.", { exact: true })).toBeVisible();
  results.push("Declared acquisition metadata and one-time binding without invented synchronization");
  }

  currentStep = "scoped credential provisioning and one-time display";
  await section(page, "Identity & access");
  const viewerToken = await issue(page, `${id}-viewer`, "viewer");
  const deviceToken = await issue(page, `${id}-principal-device`, "device", device);
  results.push("Scoped viewer/device provisioning through UI; one-time secrets dismissed and absent from HTML");
  currentStep = "viewer scope, write denial and mobile evidence";
  expect(await page.evaluate(() => ({ local: localStorage.length, session: sessionStorage.length }))).toEqual({ local: 0, session: 0 });
  const viewerContext = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const viewerPage = await viewerContext.newPage(); track(viewerPage); await unlock(viewerPage, viewerToken);
  await expect(viewerPage.getByRole("button", { name: "Load synthetic demo", exact: true })).toBeDisabled();
  await expect(viewerPage.getByRole("button", { name: "Audit trail", exact: true })).toBeDisabled();
  await section(viewerPage, "Observation intervals"); await viewerPage.locator(`.recording-rail [title="${id}"]`).locator("..").click();
  await expect(viewerPage.getByRole("button", { name: "New observation", exact: true })).toBeDisabled();
  await shot(viewerPage, "mobile-viewer-observations");
  const denied = await browserRequest(viewerPage, `${prefix}/devices`, "POST", { id: `${id}-denied`, site_id: site, label: "Synthetic forbidden test device", kind: "reef", hardware_revision: "simulation-v1", source_kind: "synthetic" }); expect(denied.status()).toBe(403);
  expect((await browserRequest(viewerPage, `${base}${prefix}/audit`)).status()).toBe(403);
  if (process.env.PLATFORM_QA_REMAINING_ONLY === "1") expect([403, 404]).toContain((await browserRequest(viewerPage, `${base}${prefix}/devices/${id}-foreign-device`)).status());
  await section(viewerPage, "Identity & access");
  await expect(viewerPage.getByRole("button", { name: "Issue scoped token", exact: true })).toBeDisabled();
  results.push("One-time scoped secrets cleared, no web storage, viewer UI and API deny writes");
  await viewerContext.close();

  currentStep = "device identity boundaries and telemetry receipts";
  const deviceContext = await browser.newContext(); const devicePage = await deviceContext.newPage(); track(devicePage); await unlock(devicePage, deviceToken);
  await expect(devicePage.getByRole("button", { name: "Evidence review", exact: true })).toBeDisabled();
  await expect(devicePage.getByRole("button", { name: "Signed local lifecycle", exact: true })).toBeDisabled();
  expect((await browserRequest(devicePage, `${base}${prefix}/lifecycle/targets`)).status()).toBe(403);
  if (process.env.PLATFORM_QA_REMAINING_ONLY === "1") expect([403, 404]).toContain((await browserRequest(devicePage, `${base}${prefix}/devices/${id}-other-device`)).status());
  const envelope = { schema_version: "poseidon.telemetry.v1", device_id: device, site_id: site, boot_id: "9007199254740993", sequence: 1, observed_at: null, delivery_age_s: 0, clock_quality: { status: "unknown", method: "unknown", uncertainty_ms: null, offset_ms: null, reference: null }, provenance: { source_kind: "synthetic", source_id: `${id}-fixture`, transport: "local" }, measurements: [{ name: "temperature", value: 12.5, unit: "Cel", quality: "uncalibrated", calibration_id: null }] };
  const receipt = await api<Telemetry>(devicePage, "/telemetry", "POST", envelope); expect(receipt.duplicate).toBe(false);
  expect((await api<Telemetry>(devicePage, "/telemetry", "POST", envelope)).duplicate).toBe(true);
  await devicePage.getByRole("button", { name: "Refresh telemetry", exact: true }).click();
  await expect(devicePage.locator("summary").filter({ hasText: "sequence 1" })).toBeVisible();
  await devicePage.locator("summary").filter({ hasText: "sequence 1" }).click();
  await expect(devicePage.getByText("9007199254740993", { exact: true })).toBeVisible();
  await expect(devicePage.locator("#telemetry-title").locator("..").locator("..").locator("..")).toContainText("uncalibrated");
  results.push("Device login/scope denial, authenticated synthetic telemetry query/idempotency, exact uint64 boot text and units");
  await deviceContext.close();

  inspectedPage = page;
  currentStep = "public trust key and local target creation";
  await section(page, "Signed local lifecycle");
  const keyId = `${id}-key`; const targetId = `${id}-target`;
  const { privateKey, publicKey } = generateKeyPairSync("ed25519");
  const publicHex = (publicKey.export({ format: "der", type: "spki" }) as Buffer).subarray(-32).toString("hex");
  await openDetails(page, "Add an Ed25519 public trust key");
  const keyForm = formFor(page, "Trust public key locally");
  await keyForm.locator('[name="id"]').fill(keyId); await keyForm.locator('[name="site_ids"]').fill(site); await keyForm.locator('[name="public_key_hex"]').fill(publicHex); await page.getByRole("button", { name: "Trust public key locally", exact: true }).click();
  await expect(page.getByText("Public trust key stored for local validation.", { exact: true })).toBeVisible();
  const baseline = createHash("sha256").update("Synthetic declared baseline; not installed").digest("hex");
  await openDetails(page, "Create a local simulation target");
  const targetForm = formFor(page, "Create simulation target");
  await targetForm.locator('[name="id"]').fill(targetId); await targetForm.locator('[name="device_id"]').fill(device); await targetForm.locator('[name="initial_sha256"]').fill(baseline); await targetForm.locator('[name="initial_version"]').fill("synthetic-baseline"); await targetForm.locator('[name="security_floor"]').fill("0"); await page.getByRole("button", { name: "Create simulation target", exact: true }).click();
  await expect(page.getByLabel("Signed manifest JSON", { exact: true })).toBeVisible();
  async function stageSequence(sequence: number) {
    currentStep = `signed local stage/activate sequence ${sequence}`;
    const bytes = Buffer.from(`Synthetic local artifact ${sequence}; not firmware and never executed.`);
    const payload = { schema_version: "poseidon.signed-manifest.v1", id: `${id}-manifest-${sequence}`, kind: "update", target_kind: "reef", hardware_revision: "simulation-v1", version: `synthetic-${sequence}`, sequence, security_version: sequence === 3 ? 1 : 0, issued_at: new Date(Date.now() - 60000).toISOString(), expires_at: new Date(Date.now() + 3600000).toISOString(), artifact_sha256: createHash("sha256").update(bytes).digest("hex"), artifact_size_bytes: bytes.length, previous_sha256: baseline, config: { monitor_only: true, telemetry_interval_s: 60, offline_queue_limit: 128 } };
    const signature = sign(null, Buffer.concat([Buffer.from("poseidon.signed-manifest.v1\0"), Buffer.from(keyId), Buffer.from("\0"), Buffer.from(canonical(payload))]), privateKey).toString("base64");
    const manifestFile = { payload, signature: { algorithm: "Ed25519", key_id: keyId, canonicalization: "poseidon-json-v1", value: signature } };
    await page.getByLabel("Signed manifest JSON", { exact: true }).setInputFiles({ name: "synthetic-signed-manifest.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(manifestFile)) }); await page.getByLabel("Exact artifact file", { exact: true }).setInputFiles({ name: "synthetic-nonexecutable-artifact.txt", mimeType: "text/plain", buffer: bytes }); await page.getByRole("button", { name: "Stage signed artifact locally", exact: true }).click();
    await expect(page.getByRole("button", { name: "Activate local trial", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Activate local trial", exact: true }).click();
    await expect(page.getByRole("button", { name: "Confirm declared local test health", exact: true })).toBeEnabled();
  }
  await stageSequence(1); currentStep = "local rollback"; await page.getByRole("button", { name: "Roll back local target", exact: true }).click(); await expect(page.getByRole("button", { name: "Stage signed artifact locally", exact: true })).toBeEnabled();
  await stageSequence(2); currentStep = "local recovery"; await page.getByRole("button", { name: "Recover local target", exact: true }).click(); await expect(page.getByRole("button", { name: "Stage signed artifact locally", exact: true })).toBeEnabled();
  await stageSequence(3); currentStep = "declared local health confirmation"; await page.getByRole("button", { name: "Confirm declared local test health", exact: true }).click(); await expect(page.getByRole("button", { name: "Confirm declared local test health", exact: true })).toBeDisabled();
  const targetState = await api<{ state: string; security_floor: number; highest_sequence: number; simulation: boolean }>(page, `/lifecycle/targets/${targetId}`);
  expect(targetState).toMatchObject({ state: "healthy", security_floor: 1, highest_sequence: 3, simulation: true });
  const transitionHistory = await api<ApiPage<{ action: string }>>(page, `/lifecycle/targets/${targetId}/history`);
  for (const action of ["stage", "activate", "rollback", "recover", "confirm"]) expect(transitionHistory.items.some((row) => row.action === action)).toBe(true);
  await shot(page, "desktop-local-lifecycle");
  const trustDetails = await openDetails(page, keyId);
  await trustDetails.getByRole("button", { name: "Revoke public trust key", exact: true }).click();
  await expect(page.getByText("Public trust key revoked.", { exact: true })).toBeVisible();
  results.push("Public trust key create/revoke, signed exact-byte staging, activate/rollback/recover/confirm UI and transition history");

  currentStep = "principal token rotation/revocation";
  await section(page, "Identity & access");
  const viewerDetails = await openDetails(page, `${id}-viewer`);
  await viewerDetails.getByRole("button", { name: "Rotate token", exact: true }).click();
  const replacementField = page.locator(".one-time-secret input"); await replacementField.waitFor();
  const replacementToken = await replacementField.inputValue(); secrets.add(replacementToken);
  await page.getByRole("button", { name: "I stored the token; clear display", exact: true }).click();
  const probe = await browser.newContext();
  expect((await sessionStatus(probe, viewerToken))).toBe(401);
  expect((await sessionStatus(probe, replacementToken))).toBe(200);
  const rotatedDetails = await openDetails(page, `${id}-viewer`);
  await rotatedDetails.getByRole("button", { name: "Revoke principal", exact: true }).click();
  await expect(page.getByText(`Revoked ${id}-viewer.`, { exact: true })).toBeVisible();
  expect((await sessionStatus(probe, replacementToken))).toBe(401);
  await probe.close();
  results.push("Explicit token rotation and revocation invalidate previous credentials");

  currentStep = "device credential revocation";
  await section(page, "Devices & telemetry");
  await page.locator(".recording-row").filter({ hasText: `${device} · site ${site}` }).click();
  await page.getByRole("button", { name: "Revoke device and its credentials", exact: true }).click();
  await expect(page.getByText("Device revoked. This changed local authorization, not physical hardware.", { exact: true })).toBeVisible();
  const revokedProbe = await browser.newContext();
  expect((await sessionStatus(revokedProbe, deviceToken))).toBe(401);
  await revokedProbe.close();
  results.push("Device revocation through UI invalidates its scoped credentials");

  currentStep = "security audit and mobile registry";
  await section(page, "Audit trail"); await expect(page.getByRole("heading", { name: "Security audit trail", exact: true })).toBeVisible();
  const audit = await api<ApiPage<unknown>>(page, "/audit"); expect(audit.total).toBeGreaterThan(0);
  await expect(page.locator(".platform-panel summary").first()).toBeVisible();
  await page.locator(".platform-panel summary").first().click();
  await expect(page.getByRole("heading", { name: "Action detail", exact: true }).first()).toBeVisible();
  await shot(page, "desktop-audit");
  await page.setViewportSize({ width: 390, height: 844 }); await section(page, "Devices & telemetry"); await shot(page, "mobile-device-registry");
  results.push("Scoped audit populated; desktop/mobile page bounds inspected");
  expect(errors).toEqual([]);
}

try {
  await Promise.race([run(), new Promise<never>((_, reject) => { deadline = setTimeout(() => reject(new Error("Browser QA exceeded its 300-second deadline")), 300000); })]);
  writeFileSync(resolve(artifacts, "platform-browser-result.json"), JSON.stringify({ state: "passed", suite: legacyOnly ? "legacy-candidate-review-video" : "platform-workflows", checks: results, authProofs, legacyProofs, screenshots, browserErrors: errors.length }, null, 2));
  console.log(JSON.stringify({ state: "passed", suite: legacyOnly ? "legacy-candidate-review-video" : "platform-workflows", checks: results.length, screenshots: screenshots.length, browserErrors: errors.length }));
} catch (error) {
  if (process.env.PLATFORM_QA_RESIDUAL_ONLY !== "1" && inspectedPage && !inspectedPage.isClosed()) {
    // Remove any transient secret surface before persisting failure evidence.
    await inspectedPage.evaluate(() => document.querySelectorAll(".one-time-secret").forEach((element) => element.remove())).catch(() => {});
    const failureShot = resolve(artifacts, "failure-redacted.png");
    await inspectedPage.screenshot({ path: failureShot, fullPage: true }).then(() => screenshots.push(failureShot)).catch(() => {});
  }
  writeFileSync(resolve(artifacts, "platform-browser-result.json"), JSON.stringify({ state: "failed", suite: legacyOnly ? "legacy-candidate-review-video" : "platform-workflows", completedChecks: results, authProofs, legacyProofs, screenshots, browserErrors: errors.length, failedStep: currentStep, error: safeError(error) }, null, 2));
  throw new Error(safeError(error));
} finally {
  if (deadline) clearTimeout(deadline);
  if (browser) await browser.close();
}
