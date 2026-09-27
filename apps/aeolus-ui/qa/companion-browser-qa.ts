import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, renameSync } from "node:fs";
import { resolve } from "node:path";
import { chromium, expect, type Browser, type Page, type Locator } from "@playwright/test";
import type { ApiPage, Job, Recording, AcousticEvent, Waveform } from "../lib/api-types";
import type { Credential, Identity } from "../lib/platform";
import { COMPANION_UPLOAD_ROLES, COMPANION_DOCUMENT_ROLES, type CompanionUploadRole, type CompanionRetained, type LegacyExportBinding } from "../lib/companion";

type Fixture = {
  label: string; directory: string; candidates: number; context: string;
  binding: LegacyExportBinding; projection: Record<string, unknown>;
  files: Array<{ role: CompanionUploadRole; name: string; bytes: number; sha256: string }>;
};
type Host = {
  page: Page; browser: Browser; artifacts: string;
  api: <T>(page: Page, path: string, method?: string, body?: unknown) => Promise<T>;
  request: (page: Page, path: string, method?: string, body?: unknown) => Promise<{ status(): number; json(): Promise<unknown> }>;
  unlock: (page: Page, credential: string) => Promise<void>;
  section: (page: Page, name: string) => Promise<void>;
  shot: (page: Page, name: string) => Promise<void>;
  track: (page: Page) => void;
  cookie: (page: Page, credential: string, label: string) => Promise<void>;
  secret: (credential: string) => void;
  step: (label: string) => void;
  check: (label: string) => void;
  proofs: Record<string, unknown>[];
};
const prefix = "/api/backend/api/v1";
const companionPath = (fixture: Fixture) => `/recordings/${fixture.binding.mapping.recording_id}/acquisition-companion`;
const hash = (bytes: Uint8Array) => createHash("sha256").update(bytes).digest("hex");
function input(fixture: Fixture, role: CompanionUploadRole) {
  const entry = fixture.files.find((file) => file.role === role);
  if (!entry) throw new Error(`Actual-reader fixture is missing ${role}`);
  const buffer = readFileSync(resolve(fixture.directory, entry.name));
  expect(buffer.length).toBe(entry.bytes); expect(hash(buffer)).toBe(entry.sha256);
  return { name: entry.name, mimeType: role === "wav" ? "audio/wav" : "application/json", buffer };
}
async function selectFiles(page: Page, fixture: Fixture) {
  for (const role of COMPANION_UPLOAD_ROLES) await page.locator(`#companion-file-${role}`).setInputFiles(input(fixture, role));
}
async function ledger(scope: Locator, name: string, value: unknown) {
  const row = scope.locator(".platform-ledger > div").filter({ has: scope.page().getByText(name, { exact: true }) });
  await expect(row).toHaveCount(1);
  await expect(row.locator("dd")).toHaveText(value === null || value === undefined ? "Not supplied" : String(value));
}
async function postSelected(page: Page, fixture: Fixture, expectedStatus = 202) {
  const url = `${prefix}/acquisition-sessions/${fixture.context}/recordings`;
  const response = page.waitForResponse((result) => new URL(result.url()).pathname === url && result.request().method() === "POST");
  await page.getByRole("button", { name: "Import selected export", exact: true }).click();
  const result = await response;
  expect(result.status()).toBe(expectedStatus);
  return result.json() as Promise<Job>;
}
// Deliberately malformed requests still use native browser cookie authentication,
// actual FormData and the real same-origin proxy/API. No positive-response stubs.
async function multipart(page: Page, fixture: Fixture, options: { omit?: CompanionUploadRole; oversize?: boolean; corrupt?: boolean } = {}) {
  const files = COMPANION_UPLOAD_ROLES.filter((role) => role !== options.omit).map((role) => {
    const item = input(fixture, role);
    const bytes = options.oversize && role === "binding" ? Buffer.alloc(262145, 32) : Buffer.from(item.buffer);
    if (options.corrupt && role === "wav") bytes[bytes.length - 1] ^= 1;
    return { role, name: item.name, mimeType: item.mimeType, bytes: Array.from(bytes) };
  });
  return page.evaluate(async ({ path, files }) => {
    const body = new FormData();
    for (const file of files) body.append(file.role, new File([new Uint8Array(file.bytes)], file.name, { type: file.mimeType }));
    const response = await fetch(path, { method: "POST", credentials: "same-origin", body });
    return { status: response.status, data: await response.json() };
  }, { path: `${prefix}/acquisition-sessions/${fixture.context}/recordings`, files });
}

export async function runCompanionSuite(host: Host) {
  const { page: owner, browser, api, request, section, step, check, proofs } = host;
  const catalogPath = process.env.PLATFORM_QA_COMPANION_CATALOG;
  if (!catalogPath) throw new Error("Companion mode requires actual-reader prepared inputs from the owned runner");
  const catalog = JSON.parse(readFileSync(catalogPath, "utf8")) as { reader: string; synthetic: boolean; fixtures: Fixture[]; changed: Fixture };
  expect(catalog.reader).toBe("poseidon_acoustic.legacy_export_reader.validate_export_bundle");
  expect(catalog.synthetic).toBe(true);
  expect(catalog.fixtures.map((item) => item.candidates)).toEqual([1, 0, 1]);
  const [positive, zero, utf16] = catalog.fixtures;
  const site = positive.binding.mapping.site_id;
  const subject = "synthetic-ui-companion-admin";
  step("companion scoped admin credential and actual native-browser session");
  const issued = await api<Credential>(owner, "/principals", "POST", { subject, role: "admin", site_ids: [site], device_id: null });
  host.secret(issued.token);
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  try {
    const page = await context.newPage(); host.track(page); await host.unlock(page, issued.token);
    await host.cookie(page, issued.token, "companion scoped admin browser cookie");
    expect(await api<Identity>(page, "/identity")).toMatchObject({ subject, role: "admin", site_ids: [site], auth_mode: "scoped_token" });
    await expect(page.getByRole("button", { name: "Load synthetic demo", exact: true })).toBeDisabled();
    step("companion scoped synthetic device and manual-context UI setup");
    await section(page, "Devices & telemetry");
    await page.getByText("Register a synthetic or bench device", { exact: true }).click();
    for (const [label, value] of [["Device ID", positive.binding.mapping.device_id], ["Device site ID", site], ["Device label", "Synthetic companion reader fixture; no physical connection"], ["Hardware revision", "simulation-v1"]]) await page.getByLabel(label, { exact: true }).fill(value);
    await page.getByRole("button", { name: "Register local test device", exact: true }).click();
    await expect(page.getByText(`Registered ${positive.binding.mapping.device_id}. Registration does not establish a connection.`, { exact: true })).toBeVisible();
    for (const fixture of [positive, utf16]) {
      await section(page, "Acquisition sessions");
      const summary = page.locator("summary").filter({ hasText: "Declare an acquisition session" });
      if (await summary.locator("..").getAttribute("open") === null) await summary.click();
      for (const [label, value] of [["Session ID", fixture.context], ["Session site ID", site], ["Session device ID (optional)", fixture.binding.mapping.device_id], ["Exact source ID", fixture.binding.source_id], ["Declared session operator", "Synthetic UI manual context operator"], ["Session notes", "Manual scope only; unknown clock does not replace imported declarations."]]) await page.getByLabel(label, { exact: true }).fill(value);
      await page.getByRole("button", { name: "Store declared session", exact: true }).click();
      await expect(page.getByText(`Stored acquisition session ${fixture.context}. No capture or synchronization was performed.`, { exact: true })).toBeVisible();
    }
    check("Scoped admin creates a real synthetic device and two manual contexts through existing UI; native HttpOnly cookie auth, legacy demo remains disabled");
    const saved: Record<string, CompanionRetained> = {};
    for (const fixture of catalog.fixtures) {
      step(`companion ${fixture.label} seven-role UI upload and real replay`);
      await section(page, "Imported companions");
      await expect(page.locator('.companion-import input[type="file"]')).toHaveCount(7);
      await page.getByLabel("Existing platform session", { exact: true }).selectOption(fixture.context);
      await selectFiles(page, fixture);
      await expect(page.getByRole("button", { name: "Import selected export", exact: true })).toBeEnabled();
      let job = await postSelected(page, fixture);
      const firstJobId = job.id;
      for (let attempt = 0; attempt < 150 && ["queued", "running"].includes(job.status); attempt++) { await page.waitForTimeout(100); job = await api<Job>(page, `/jobs/${job.id}`); }
      expect(job.status).toBe("succeeded");
      const recording = await api<Recording>(page, `/recordings/${job.recording_id}`);
      expect(recording.event_count).toBe(fixture.candidates);
      const view = page.locator(".companion-panel");
      await expect(view.locator(".companion-processing")).toContainText("Replay processing: succeeded", { timeout: 15000 });
      const retained = await api<CompanionRetained>(page, companionPath(fixture));
      expect(retained).toMatchObject({ state: "retained", recording_id: fixture.binding.mapping.recording_id, platform_session_id: fixture.context, capture_session_id: fixture.binding.session_id, source_id: fixture.binding.source_id, selected_index: fixture.binding.mapping.segment_index, actor_subject: subject, auth_mode: "scoped_token" });
      expect(retained.binding).toEqual(fixture.binding); expect(retained.validation).toEqual(fixture.projection);
      saved[fixture.label] = retained;
      await ledger(view, "Manual platform context ID", fixture.context);
      await ledger(view, "Source capture-session ID", fixture.binding.session_id);
      await ledger(view, "Selected segment index", fixture.binding.mapping.segment_index);
      await ledger(view, "Authenticated importer", subject);
      const channelRows = view.locator(".companion-channels tbody tr");
      await expect(channelRows).toHaveCount(2);
      for (const [index, channel] of fixture.binding.source.channels.entries()) expect(await channelRows.nth(index).locator("th,td").allTextContents()).toEqual([String(index), channel.channel_id, channel.role]);
      expect(fixture.binding.source.channels.map((channel) => channel.channel_id)).toEqual(["right", "left"]);
      const timing = fixture.binding.time;
      for (const [name, value] of [["Nominal duration (s)", timing.nominal_duration_s], ["Reference duration (s)", timing.reference_duration_s], ["Derived declared start (UTC)", timing.started_at], ["Nominal WAV end (UTC)", timing.nominal_wav_ended_at], ["Reference end (UTC)", timing.reference_ended_at], ["Combined start uncertainty (s)", timing.combined_start_uncertainty_s], ["Combined end uncertainty (s)", timing.combined_end_uncertainty_s], ["Start rounding error (s)", timing.started_at_rounding_error_s], ["Reference-end rounding error (s)", timing.reference_end_rounding_error_s], ["Declared epoch (UTC)", timing.epoch_declaration.epoch_utc]]) await ledger(view, name, value);
      const receipt = fixture.binding.original_receipt.record;
      for (const [name, value] of [["Declared source gap (s)", receipt.gap_source_s], ["Missing units", receipt.missing_units], ["Dropped units", receipt.dropped_units], ["Unexplained missing units", receipt.unexplained_missing_units]]) await ledger(view, String(name), value);
      await expect(view.locator(".companion-coverage")).toContainText("Stored segments only; trailing capture extent is not attested.");
      for (const flag of ["original_input_bytes_verified", "full_original_session_bytes_verified", "clock_relation_verified", "epoch_declaration_verified", "origin_verified", "authorization_verified", "calibration_verified", "acquisition_completeness_verified"]) {
        expect((retained.validation.verification as Record<string, unknown>)[flag]).toBe(false);
        await expect(view.getByLabel("Reader verification coverage", { exact: true })).toContainText(`"${flag}": false`);
      }
      step(`companion ${fixture.label} exact five browser downloads`);
      const documents: Record<string, unknown>[] = [];
      for (const role of COMPANION_DOCUMENT_ROLES) {
        const original = input(fixture, role);
        const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === `${prefix}${companionPath(fixture)}/documents/${role}`);
        const downloadPromise = page.waitForEvent("download");
        await view.getByRole("button", { name: `Download ${role}`, exact: true }).click();
        const response = await responsePromise; expect(response.status()).toBe(200);
        const headers = response.headers();
        expect(headers["content-type"]).toBe("application/json"); expect(headers["cache-control"]).toBe("no-store"); expect(headers["x-content-type-options"]).toBe("nosniff");
        expect(headers["content-disposition"]).toBe(`attachment; filename="${original.name}"`);
        expect(headers["x-poseidon-document-sha256"]).toBe(hash(original.buffer));
        const download = await downloadPromise; expect(download.suggestedFilename()).toBe(original.name);
        const destination = resolve(host.artifacts, `platform-tranche2-ui-${fixture.label}-${role}.json`);
        await download.saveAs(destination);
        expect(readFileSync(destination).equals(original.buffer)).toBe(true);
        documents.push({ role, name: original.name, bytes: original.buffer.length, sha256: hash(original.buffer), exactDownloadedBytes: true, saved: destination });
      }
      if (fixture.label === "zero-candidate") {
        expect(receipt.gap_source_s).toBe(0.98); expect(receipt.missing_units).toBe(7840); expect(receipt.dropped_units).toBe(100);
        await host.shot(page, "platform-tranche2-ui-companion-desktop");
        await page.setViewportSize({ width: 390, height: 844 });
        await host.shot(page, "platform-tranche2-ui-companion-mobile");
        await page.setViewportSize({ width: 1440, height: 1000 });
      }
      if (fixture.label === "utf16-final") {
        expect(input(fixture, "source_final").buffer.subarray(0, 2).toString("hex")).toBe("fffe");
        await ledger(view, "Epoch declared by", "<img src=x onerror=syntheticOnly()>");
        await ledger(view, "Epoch evidence reference (inert text)", "javascript:syntheticOnly()");
        await expect(view.locator("img, iframe, a[href^='javascript:']")).toHaveCount(0);
      }
      step(`companion ${fixture.label} exact retry keeps job and importer`);
      const retry = await postSelected(page, fixture);
      expect(retry.id).toBe(firstJobId);
      expect(await api<CompanionRetained>(page, companionPath(fixture))).toEqual(retained);
      check(`${fixture.label}: seven original UI files, actual reader/projection, ${fixture.candidates} candidates, ordered stereo, exact declared timing/coverage, all five raw UI downloads and qualified retry`);
      proofs.push({ operation: fixture.label, reader: catalog.reader, originalDirectory: fixture.directory, recordingId: job.recording_id, platformSessionId: fixture.context, captureSessionId: fixture.binding.session_id, selectedIndex: fixture.binding.mapping.segment_index, jobId: job.id, candidateCount: recording.event_count, channels: fixture.binding.source.channels, time: timing, selectedReceipt: receipt, exactBindingAndReaderProjection: true, documents, exactRetrySameJobAndImporter: true });
    }
    step("companion valid changed-budget 409 preserves originals and UI selections");
    await page.getByLabel("Existing platform session", { exact: true }).selectOption(positive.context);
    await selectFiles(page, catalog.changed); await postSelected(page, catalog.changed, 409);
    await expect(page.locator(".companion-problem")).toContainText("Identity, binding or capacity conflict.");
    expect(await page.locator('#companion-file-binding').evaluate((element) => (element as HTMLInputElement).files?.length)).toBe(1);
    expect(await api<CompanionRetained>(page, companionPath(positive))).toEqual(saved.positive);
    check("Reader-valid changed companion returns 409; original job/actor/projection/documents and selected UI files remain unchanged");
    step("companion incomplete, corrupt and oversized multipart errors");
    expect((await multipart(page, positive, { omit: "binding" })).status).toBe(400);
    expect((await multipart(page, positive, { corrupt: true })).status).toBe(400);
    expect((await multipart(page, positive, { oversize: true })).status).toBe(413);
    // Client preflight rejects an oversize role before posting, without trimming it.
    let unexpectedPosts = 0;
    const countPost = (request: import("@playwright/test").Request) => { if (request.method() === "POST" && new URL(request.url()).pathname.endsWith(`/${positive.context}/recordings`)) unexpectedPosts++; };
    page.on("request", countPost);
    await page.locator("#companion-file-binding").setInputFiles({ name: "oversize-binding.json", mimeType: "application/json", buffer: Buffer.alloc(262145, 32) });
    await page.getByRole("button", { name: "Import selected export", exact: true }).click();
    await expect(page.locator(".companion-problem")).toContainText("exceeds its 262144-byte local limit");
    page.off("request", countPost); expect(unexpectedPosts).toBe(0);
    expect((await api<ApiPage<Job>>(page, "/jobs")).total).toBe(3);
    check("Real API rejects incomplete/corrupt packages with 400 and oversize with 413; UI preflight preserves oversized bytes without posting or legacy fallback");
    step("companion positive waveform retains existing nominal seconds");
    await page.getByRole("button", { name: "Clear file selection", exact: true }).click();
    await section(page, "Evidence review");
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await page.locator(`.recording-rail [title="${positive.binding.mapping.recording_id}"]`).locator("..").click();
    const events = await api<ApiPage<AcousticEvent>>(page, `/events?recording_id=${positive.binding.mapping.recording_id}`);
    expect(events.total).toBe(1);
    await page.locator(".event-row").filter({ has: page.locator(`[title="${events.items[0].event_id}"]`) }).click();
    const waveform = await api<Waveform>(page, `/recordings/${positive.binding.mapping.recording_id}/waveform?points=512`);
    await expect(page.locator(".waveform-chart")).toBeVisible();
    await expect(page.locator(".waveform-figure")).toContainText("normalized PCM16 full-scale · not SPL");
    expect(waveform.buckets[0].start_s).toBe(0); expect(waveform.buckets.at(-1)?.end_s).toBe(Number(positive.binding.time.nominal_duration_s));
    check("Existing positive candidate waveform remains source-derived nominal segment seconds, normalized PCM16, not SPL or candidate UTC");
    step("companion legacy metadata absence without silent backfill");
    // The old route remains development-only. Import a distinct legacy manifest
    // with existing synthetic WAV bytes, then bind through the old explicit route.
    const legacyId = "synthetic-ui-companion-legacy";
    const legacyManifest = { ...(positive.projection.manifest as Record<string, unknown>), recording_id: legacyId };
    const legacyResponse = await owner.evaluate(async ({ prefix, manifest, wav }) => {
      const body = new FormData(); body.append("wav", new File([new Uint8Array(wav)], "synthetic-legacy.wav", { type: "audio/wav" })); body.append("manifest", new File([JSON.stringify(manifest)], "synthetic-legacy.json", { type: "application/json" }));
      const response = await fetch(`${prefix}/recordings`, { method: "POST", credentials: "same-origin", body });
      return { status: response.status, data: await response.json() };
    }, { prefix, manifest: legacyManifest, wav: Array.from(input(positive, "wav").buffer) });
    expect(legacyResponse.status).toBe(202);
    let legacyJob = legacyResponse.data as Job;
    for (let attempt = 0; attempt < 150 && ["queued", "running"].includes(legacyJob.status); attempt++) { await owner.waitForTimeout(100); legacyJob = await api<Job>(owner, `/jobs/${legacyJob.id}`); }
    expect(legacyJob.status).toBe("succeeded");
    await api(owner, `/recordings/${legacyId}/acquisition-session`, "PUT", { session_id: positive.context });
    await section(page, "Imported companions");
    await page.getByLabel("Exact recording ID", { exact: true }).fill(legacyId); await page.getByRole("button", { name: "Inspect companions", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Legacy record: companions not retained", exact: true })).toBeVisible();
    expect(await api(page, `/recordings/${legacyId}/acquisition-companion`)).toEqual({ schema_version: "poseidon.recording-acquisition-companion.v1", state: "absent", recording_id: legacyId });
    expect((await request(page, `${prefix}/recordings/${legacyId}/acquisition-companion/documents/binding`)).status()).toBe(404);
    await expect(page.locator(".companion-downloads")).toHaveCount(0);
    check("Known explicitly bound legacy record shows absent companions, no downloads and no metadata backfill");
    step("companion viewer and foreign-admin scope through native browser sessions");
    for (const [label, role, sites] of [["viewer", "viewer", [site]], ["foreign", "admin", ["synthetic-ui-foreign-site"]]] as const) {
      const credential = await api<Credential>(owner, "/principals", "POST", { subject: `synthetic-ui-companion-${label}`, role, site_ids: [...sites], device_id: null }); host.secret(credential.token);
      const scoped = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      try {
        const scopedPage = await scoped.newPage(); host.track(scopedPage); await host.unlock(scopedPage, credential.token); await section(scopedPage, "Imported companions");
        await scopedPage.getByLabel("Exact recording ID", { exact: true }).fill(positive.binding.mapping.recording_id); await scopedPage.getByRole("button", { name: "Inspect companions", exact: true }).click();
        if (label === "viewer") {
          await expect(scopedPage.getByRole("button", { name: "Import selected export", exact: true })).toBeDisabled();
          await expect(scopedPage.locator(".companion-panel .companion-channels")).toBeVisible();
          expect((await multipart(scopedPage, positive)).status).toBe(403);
          expect((await request(scopedPage, `${prefix}${companionPath(positive)}/documents/binding`)).status()).toBe(200);
        } else {
          await expect(scopedPage.locator(".companion-panel [role=alert]")).toContainText("Context or record unavailable in this scope.");
          await expect(scopedPage.locator(".companion-downloads")).toHaveCount(0);
          expect((await multipart(scopedPage, positive)).status).toBe(404);
          expect((await request(scopedPage, `${prefix}${companionPath(positive)}/documents/binding`)).status()).toBe(404);
        }
      } finally { await scoped.close(); }
    }
    check("Viewer can inspect but cannot upload (403); foreign admin receives hidden 404 on metadata, raw document and upload with no retained evidence rendered");
    step("companion revocation clears previously rendered evidence and cookie");
    await page.getByLabel("Exact recording ID", { exact: true }).fill(positive.binding.mapping.recording_id); await page.getByRole("button", { name: "Inspect companions", exact: true }).click();
    await expect(page.getByRole("button", { name: "Download binding", exact: true })).toBeVisible();
    await api(owner, `/principals/${issued.principal.id}/revoke`, "POST");
    const revokedRead = page.waitForResponse((response) => new URL(response.url()).pathname === `${prefix}${companionPath(positive)}`);
    await page.getByRole("button", { name: "Refresh retained evidence", exact: true }).click();
    expect((await revokedRead).status()).toBe(401);
    await expect(page.locator(".companion-downloads")).toHaveCount(0);
    expect((await request(page, `${prefix}${companionPath(positive)}/documents/binding`)).status()).toBe(401);
    expect((await multipart(page, positive)).status).toBe(401);
    expect((await context.cookies()).some((cookie) => cookie.name === "poseidon_session")).toBe(false);
    await page.reload({ waitUntil: "domcontentloaded" }); await expect(page.getByLabel("Local access key", { exact: true })).toBeVisible();
    check("Revoked scoped admin gets 401 on refresh/raw/upload, stale evidence is removed, cookie clears and AccessGate returns");
    proofs.push({ operation: "errors-and-scope", validChangedCompanion: 409, missingRole: 400, corruptWav: 400, oversizeBinding: 413, uiOversizePosts: 0, viewerUpload: 403, foreignMetadataRawUpload: 404, revokedMetadataRawUpload: 401, legacyState: "absent", physicalOperation: false });
  } finally { await context.close(); }
}

async function main() {
  const base = process.env.UI_BASE_URL ?? "";
  const token = process.env.POSEIDON_ACCESS_TOKEN ?? "";
  const artifacts = process.env.PLATFORM_QA_ARTIFACTS ?? "";
  if (process.env.PLATFORM_QA_OWNED_WORKSPACE !== "1" || process.env.PLATFORM_QA_COMPANION_ONLY !== "1" || !token || !artifacts || !["127.0.0.1", "localhost"].includes(new URL(base).hostname)) throw new Error("Companion QA requires the owned loopback runner and temporary credential");
  const origin = new URL(base).origin;
  const secrets = new Set([token]);
  const checks: string[] = [];
  const proofs: Record<string, unknown>[] = [];
  const screenshots: string[] = [];
  const errors: string[] = [];
  let currentStep = "owned companion workspace login";
  let browser: Browser | undefined;
  let inspected: Page | undefined;
  let deadline: ReturnType<typeof setTimeout> | undefined;
  const ownedUrl = (path: string) => { const url = new URL(path, origin); if (url.origin !== origin || url.username || url.password) throw new Error("Companion request left its owned origin"); return url.href; };
  const request: Host["request"] = async (page, path, method = "GET", body) => {
    const result = await page.evaluate(async ({ url, method, payload, hasBody }) => {
      const response = await fetch(url, { method, credentials: "same-origin", cache: "no-store", headers: hasBody ? { "content-type": "application/json" } : { accept: "application/json" }, ...(hasBody ? { body: JSON.stringify(payload) } : {}) });
      return { status: response.status, data: await response.json().catch(() => null) };
    }, { url: ownedUrl(path), method, payload: body ?? null, hasBody: body !== undefined });
    return { status: () => result.status, json: async () => result.data };
  };
  const api: Host["api"] = async <T,>(page: Page, path: string, method = "GET", body?: unknown): Promise<T> => {
    const response = await request(page, `${prefix}${path}`, method, body);
    if (response.status() < 200 || response.status() >= 300) throw new Error(`${method} ${path} returned HTTP ${response.status()}`);
    return await response.json() as T;
  };
  const track = (page: Page) => { inspected = page; page.setDefaultTimeout(15000); page.on("pageerror", () => errors.push("browser pageerror")); page.on("dialog", (dialog) => void dialog.accept()); };
  const unlock: Host["unlock"] = async (page, credential) => {
    secrets.add(credential); inspected = page; await page.bringToFront();
    await page.goto(ownedUrl("/"), { waitUntil: "domcontentloaded" });
    await page.getByLabel("Local access key", { exact: true }).fill(credential);
    const responsePromise = page.waitForResponse((response) => response.url() === ownedUrl("/api/session") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Unlock workspace", exact: true }).click();
    expect((await responsePromise).status()).toBe(200);
    await page.getByRole("navigation", { name: "Workbench sections" }).waitFor();
  };
  const section: Host["section"] = async (page, name) => { inspected = page; await page.bringToFront(); await page.getByRole("navigation", { name: "Workbench sections" }).getByRole("button", { name, exact: true }).click(); };
  const shot: Host["shot"] = async (page, name) => {
    if (await page.locator(".one-time-secret").count()) throw new Error("Refusing a screenshot of a transient credential panel");
    await page.evaluate(() => window.scrollTo(0, 0));
    const destination = resolve(artifacts, `${name}.png`); await page.screenshot({ path: destination, fullPage: true }); screenshots.push(destination);
    expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
  };
  const cookie: Host["cookie"] = async (page, credential, label) => {
    const value = (await page.context().cookies(ownedUrl("/"))).find((item) => item.name === "poseidon_session");
    if (!value) throw new Error("Actual companion browser cookie missing");
    expect(value).toMatchObject({ httpOnly: true, sameSite: "Strict", path: "/", domain: new URL(base).hostname, secure: false });
    expect(value.value === credential).toBe(true);
    expect(value.expires - Date.now() / 1000).toBeGreaterThan(28700);
    expect(value.expires - Date.now() / 1000).toBeLessThanOrEqual(28805);
    expect(await page.evaluate(() => ({ cookie: document.cookie.includes("poseidon_session="), local: localStorage.length, session: sessionStorage.length }))).toEqual({ cookie: false, local: 0, session: 0 });
    proofs.push({ operation: label, httpOnly: true, sameSite: "Strict", path: "/", actualBrowserCookieMatches: true, eightHourLifetime: true, browserStorageEmpty: true });
  };
  let failure: string | null = null;
  try {
    const execute = async () => {
      browser = await chromium.launch({ headless: true });
      const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }); track(page); await unlock(page, token);
      await runCompanionSuite({ page, browser, artifacts, api, request, unlock, section, shot, track, cookie, secret: (credential) => secrets.add(credential), step: (label) => { currentStep = label; console.log(JSON.stringify({ stage: label })); }, check: (label) => checks.push(label), proofs });
      expect(errors).toEqual([]);
    };
    await Promise.race([execute(), new Promise<never>((_, reject) => { deadline = setTimeout(() => reject(new Error("Companion browser QA exceeded its 300-second deadline")), 300000); })]);
  } catch (caught) {
    failure = caught instanceof Error ? caught.message : "Companion browser QA failed";
    for (const secret of secrets) failure = failure.split(secret).join("[REDACTED]");
    if (inspected && !inspected.isClosed()) {
      await inspected.evaluate(() => document.querySelectorAll(".one-time-secret").forEach((element) => element.remove())).catch(() => {});
      const destination = resolve(artifacts, "platform-tranche2-ui-failure-redacted.png");
      await inspected.screenshot({ path: destination, fullPage: true, timeout: 5000 }).then(() => screenshots.push(destination)).catch(() => {});
    }
  } finally {
    if (deadline) clearTimeout(deadline);
    if (browser) await browser.close();
  }
  const result = { state: failure ? "failed" : "passed", suite: "companion-single-export", skipped: 0, checks, proofs, screenshots, browserErrors: errors.length, browserClosed: true, failedStep: failure ? currentStep : null, error: failure };
  const destination = resolve(artifacts, "platform-tranche2-ui-browser-result.json");
  writeFileSync(`${destination}.tmp`, JSON.stringify(result, null, 2) + "\n"); renameSync(`${destination}.tmp`, destination);
  console.log(JSON.stringify({ state: result.state, suite: result.suite, checks: checks.length, skipped: 0, screenshots: screenshots.length, browserErrors: errors.length }));
  if (failure) throw new Error(failure);
}

if (import.meta.main) await main();
