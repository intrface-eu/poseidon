import { spawnSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { chromium, expect, type Browser, type Page, type Response } from "@playwright/test";
import type { EventDetail, Job, Review, ReviewLabel, VideoEvidence } from "../lib/api-types";

const baseUrl = process.env.UI_BASE_URL ?? "http://127.0.0.1:3100";
const round = process.env.QA_ROUND ?? "inspection";
const appRoot = process.cwd();
const repoRoot = resolve(appRoot, "..", "..");
const artifacts = resolve(appRoot, "qa", "artifacts");
const statePath = resolve(artifacts, "last-recording.json");

type QaState = {
  eventId: string;
  recordingId: string;
  reviewRevision: number;
};

function accessKey(): string {
  const direct = process.env.POSEIDON_ACCESS_TOKEN;
  if (direct) return direct.trim();
  const path = process.env.POSEIDON_ACCESS_TOKEN_FILE;
  if (!path) throw new Error("Set POSEIDON_ACCESS_TOKEN or POSEIDON_ACCESS_TOKEN_FILE for browser QA.");
  return readFileSync(path, "utf8").trim();
}

function requireOk(response: Response, operation: string) {
  if (!response.ok()) throw new Error(`${operation} returned HTTP ${response.status()}.`);
}

async function unlock(page: Page, token: string, testBadKey: boolean) {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
  const keyField = page.getByLabel("Local access key");
  const eventHeading = page.getByRole("heading", { name: "Candidate events" });
  const state = await Promise.race([
    keyField.waitFor({ state: "visible", timeout: 20_000 }).then(() => "locked" as const),
    eventHeading.waitFor({ state: "visible", timeout: 20_000 }).then(() => "ready" as const),
  ]);
  if (state === "locked") {
    if (testBadKey) {
      await keyField.fill("qa-invalid-access-key");
      await page.getByRole("button", { name: "Unlock workspace" }).click();
      await page.getByText("Access not granted.", { exact: true }).waitFor({ timeout: 20_000 });
      await expect(keyField).toBeVisible();
    }
    await keyField.fill(token);
    await page.getByRole("button", { name: "Unlock workspace" }).click();
  }
  await eventHeading.waitFor({ state: "visible", timeout: 20_000 });
  await expect(page.getByText("Monitor only", { exact: true }).first()).toBeVisible();
}

async function submitDemo(page: Page) {
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes("/api/backend/api/v1/demo") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Load synthetic demo" }).click();
  const response = await responsePromise;
  requireOk(response, "Synthetic demo submission");
  const job = (await response.json()) as Job;
  await waitForJob(page, job);
}

async function waitForJob(page: Page, submitted: Job): Promise<Job> {
  let latest = submitted;
  const deadline = Date.now() + 60_000;
  while (latest.status === "queued" || latest.status === "running") {
    if (Date.now() > deadline) throw new Error(`Job ${submitted.id} did not reach a terminal state.`);
    await page.waitForTimeout(250);
    latest = await page.evaluate(async (jobId) => {
      const response = await fetch(`/api/backend/api/v1/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Job polling returned ${response.status}.`);
      return response.json();
    }, submitted.id) as Job;
  }
  if (latest.status !== "succeeded") throw new Error(latest.error ?? `Job ${latest.id} failed.`);
  const jobRow = page.getByTitle(latest.id).locator("..");
  await expect(jobRow).toContainText("succeeded", { timeout: 20_000 });
  return latest;
}

function runFixtureCommand(command: string[], env?: NodeJS.ProcessEnv) {
  const result = spawnSync(command[0], command.slice(1), {
    cwd: repoRoot,
    env: env ?? process.env,
    stdio: ["ignore", "ignore", "pipe"],
  });
  if (result.status !== 0) throw new Error(`Fixture command ${command[0]} failed with status ${result.status}.`);
}

function createRecordingFixture(tempRoot: string) {
  const fixtureDir = join(tempRoot, "recording");
  const pythonPath = [
    resolve(repoRoot, "libs/proto-py/src"),
    resolve(repoRoot, "apps/acoustic/src"),
    process.env.PYTHONPATH,
  ].filter(Boolean).join(":");
  runFixtureCommand(
    ["python3", "-m", "poseidon_acoustic", "demo", "--output-dir", fixtureDir],
    { ...process.env, PYTHONPATH: pythonPath },
  );

  const manifestPath = join(fixtureDir, "recording-manifest.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
  const recordingId = `synthetic-browser-qa-${Date.now()}`;
  manifest.recording_id = recordingId;
  manifest.site_id = "synthetic-browser-qa-site";
  manifest.zone_id = "synthetic-browser-qa-zone";
  manifest.device_id = "synthetic-browser-qa-device";
  manifest.started_at = new Date().toISOString();
  writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`, "utf8");
  return {
    manifestPath,
    recordingId,
    wavPath: join(fixtureDir, "synthetic.wav"),
  };
}

function createVideoFixture(tempRoot: string): string {
  const sourcePath = join(tempRoot, "generate-synthetic-video.swift");
  const videoPath = join(tempRoot, "synthetic-visual-evidence.mp4");
  writeFileSync(sourcePath, String.raw`import AVFoundation
import CoreVideo
import Foundation

let output = URL(fileURLWithPath: CommandLine.arguments[1])
let writer = try AVAssetWriter(outputURL: output, fileType: .mp4)
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: 320,
    AVVideoHeightKey: 240,
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let attributes: [String: Any] = [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
    kCVPixelBufferWidthKey as String: 320,
    kCVPixelBufferHeightKey as String: 240,
]
let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: attributes)
if !writer.canAdd(input) { throw NSError(domain: "SyntheticVideo", code: 1) }
writer.add(input)
if !writer.startWriting() { throw writer.error ?? NSError(domain: "SyntheticVideo", code: 2) }
writer.startSession(atSourceTime: .zero)
var optionalBuffer: CVPixelBuffer?
CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &optionalBuffer)
let buffer = optionalBuffer!
CVPixelBufferLockBaseAddress(buffer, [])
let base = CVPixelBufferGetBaseAddress(buffer)!.assumingMemoryBound(to: UInt8.self)
let rowBytes = CVPixelBufferGetBytesPerRow(buffer)
for y in 0..<240 {
    for x in 0..<320 {
        let offset = y * rowBytes + x * 4
        let marker = x > 32 && x < 288 && y > 96 && y < 144
        base[offset] = marker ? 0xEE : 0x66
        base[offset + 1] = marker ? 0xF7 : 0x59
        base[offset + 2] = marker ? 0xF7 : 0x0D
        base[offset + 3] = 0xFF
    }
}
CVPixelBufferUnlockBaseAddress(buffer, [])
for frame in 0..<2 {
    while !input.isReadyForMoreMediaData { Thread.sleep(forTimeInterval: 0.01) }
    let time = CMTime(value: CMTimeValue(frame * 15), timescale: 30)
    if !adaptor.append(buffer, withPresentationTime: time) { throw writer.error ?? NSError(domain: "SyntheticVideo", code: 3) }
}
writer.endSession(atSourceTime: CMTime(value: 30, timescale: 30))
input.markAsFinished()
let semaphore = DispatchSemaphore(value: 0)
writer.finishWriting { semaphore.signal() }
semaphore.wait()
if writer.status != .completed { throw writer.error ?? NSError(domain: "SyntheticVideo", code: 4) }
`, "utf8");
  runFixtureCommand(["/usr/bin/swift", sourcePath, videoPath]);
  return videoPath;
}

async function ensureImportForm(page: Page) {
  const wavInput = page.getByLabel("WAV recording");
  if (!await wavInput.isVisible().catch(() => false)) {
    await page.getByRole("button", { name: "Import WAV + manifest" }).click();
  }
  await wavInput.waitFor();
}

async function importRecording(
  page: Page,
  fixture: ReturnType<typeof createRecordingFixture>,
) {
  await ensureImportForm(page);
  await page.getByLabel("WAV recording").setInputFiles({
    buffer: readFileSync(fixture.wavPath),
    mimeType: "audio/wav",
    name: "synthetic-browser-qa.wav",
  });
  await page.getByLabel("Recording manifest").setInputFiles({
    buffer: readFileSync(fixture.manifestPath),
    mimeType: "application/json",
    name: "recording-manifest.json",
  });
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/api/backend/api/v1/recordings") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Submit recording" }).click();
  const response = await responsePromise;
  requireOk(response, "WAV and manifest import");
  const job = (await response.json()) as Job;
  await waitForJob(page, job);
}

async function selectRecordingEvent(page: Page, recordingId: string, eventId?: string) {
  const recordingSelect = page.getByLabel("Recording").last();
  await page.waitForFunction(
    (id) => Array.from(document.querySelectorAll("select option")).some((option) => (option as HTMLOptionElement).value === id),
    recordingId,
    { timeout: 30_000 },
  );
  await recordingSelect.selectOption(recordingId);
  const eventRows = page.locator(".event-row");
  await eventRows.first().waitFor({ timeout: 30_000 });
  if (eventId) {
    const row = page.getByTitle(eventId).locator("xpath=ancestor::button[contains(@class, 'event-row')]");
    await row.click();
  } else {
    await eventRows.first().click();
  }
  await page.getByRole("img", { name: /Normalized waveform envelope/ }).waitFor({ timeout: 30_000 });
  return (await page.locator(".event-identifier").textContent())?.trim() ?? null;
}

async function saveInitialReview(page: Page): Promise<Review> {
  await page.getByLabel("Observation label").selectOption("uncertain");
  await page.getByLabel("Reviewer").fill("Browser QA operator");
  await page.getByLabel(/Notes/).fill("Synthetic fixture reviewed during the bounded browser QA pass.");
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/review") && response.request().method() === "PUT",
  );
  await page.getByRole("button", { name: "Save review" }).click();
  const response = await responsePromise;
  requireOk(response, "Initial review save");
  const review = (await response.json()) as Review;
  if (review.label !== "uncertain" || review.reviewer !== "Browser QA operator" || review.revision < 1) {
    throw new Error("Initial review response did not contain the persisted values.");
  }
  return review;
}

async function verifyReviewAfterReload(page: Page, recordingId: string, eventId: string, review: Review) {
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Candidate events" }).waitFor({ timeout: 20_000 });
  await selectRecordingEvent(page, recordingId, eventId);
  await expect(page.getByLabel("Observation label")).toHaveValue(review.label);
  await expect(page.getByLabel("Reviewer")).toHaveValue(review.reviewer);
  await expect(page.getByLabel(/Notes/)).toHaveValue(review.notes);
  await expect(page.locator(".review-block .revision-stamp")).toContainText(`revision ${review.revision}`);
}

async function proveRevisionConflict(page: Page, eventId: string, base: Review): Promise<Review> {
  const preservedNotes = "This unsaved draft must survive a stale-revision response.";
  const preservedReviewer = "Browser QA draft operator";
  await page.getByLabel("Observation label").selectOption("confirmed_feeding");
  await page.getByLabel("Reviewer").fill(preservedReviewer);
  await page.getByLabel(/Notes/).fill(preservedNotes);

  const concurrent = await page.evaluate(async ({ id, revision }) => {
    const response = await fetch(`/api/backend/api/v1/events/${encodeURIComponent(id)}/review`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        label: "non_feeding",
        notes: "Concurrent same-session QA update.",
        reviewer: "Concurrent QA actor",
        expected_revision: revision,
      }),
    });
    return { body: await response.json(), status: response.status };
  }, { id: eventId, revision: base.revision });
  if (concurrent.status !== 200) throw new Error(`Concurrent review setup returned ${concurrent.status}.`);
  const concurrentReview = concurrent.body as Review;

  const conflictPromise = page.waitForResponse(
    (response) => response.url().endsWith("/review") && response.request().method() === "PUT" && response.status() === 409,
  );
  await page.getByRole("button", { name: "Save review" }).click();
  await conflictPromise;
  await page.getByText("Revision conflict.", { exact: true }).waitFor({ timeout: 20_000 });
  await expect(page.getByLabel("Reviewer")).toHaveValue(preservedReviewer);
  await expect(page.getByLabel(/Notes/)).toHaveValue(preservedNotes);

  const retryPromise = page.waitForResponse(
    (response) => response.url().endsWith("/review") && response.request().method() === "PUT" && response.status() === 200,
  );
  await page.getByRole("button", { name: `Save my draft over revision ${concurrentReview.revision}` }).click();
  const retryResponse = await retryPromise;
  const persisted = (await retryResponse.json()) as Review;
  if (persisted.revision !== concurrentReview.revision + 1 || persisted.notes !== preservedNotes) {
    throw new Error("The preserved conflict draft was not persisted at the next revision.");
  }
  return persisted;
}

async function attachVideo(page: Page, videoPath: string): Promise<VideoEvidence> {
  await page.getByLabel("MP4 evidence").setInputFiles({
    buffer: readFileSync(videoPath),
    mimeType: "video/mp4",
    name: "synthetic-visual-evidence.mp4",
  });
  await page.getByLabel("Declared offset (seconds)").fill("0.125");
  const responsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/video") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Attach video evidence" }).click();
  const response = await responsePromise;
  requireOk(response, "Video evidence attachment");
  const metadata = (await response.json()) as VideoEvidence;
  if (metadata.alignment !== "operator_declared" || metadata.offset_s !== 0.125) {
    throw new Error("Video metadata did not preserve the declared alignment state.");
  }
  await expect(page.getByText("Unverified · operator declared", { exact: true })).toBeVisible();
  await expect(page.getByText("+0.125 s", { exact: true })).toBeVisible();
  const video = page.locator("video");
  await video.waitFor({ state: "visible" });
  await page.waitForFunction(() => {
    const element = document.querySelector("video") as HTMLVideoElement | null;
    return Boolean(element && element.readyState >= 1 && Number.isFinite(element.duration));
  }, undefined, { timeout: 20_000 });
  await expect(page.getByText("Browser decoder could not open this MP4.", { exact: true })).toHaveCount(0);
  return metadata;
}

async function proveLogoutAndRecovery(page: Page, token: string) {
  await page.getByRole("button", { name: "Lock workspace" }).click();
  await page.getByLabel("Local access key").waitFor({ timeout: 20_000 });
  const deniedStatus = await page.evaluate(async () => (await fetch("/api/backend/api/v1/status", { cache: "no-store" })).status);
  if (deniedStatus !== 401) throw new Error(`Logged-out data request returned ${deniedStatus}, not 401.`);
  await unlock(page, token, false);
}

async function proveSimulatedNetworkRecovery(page: Page) {
  const pattern = "**/api/backend/api/v1/status";
  await page.route(pattern, (route) => route.abort("connectionfailed"));
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Local API unavailable" }).waitFor({ timeout: 20_000 });
  await page.unroute(pattern);
  await page.getByRole("button", { name: "Retry connection" }).click();
  await page.getByRole("heading", { name: "Candidate events" }).waitFor({ timeout: 20_000 });
}

async function fetchEventDetail(page: Page, eventId: string): Promise<EventDetail> {
  return await page.evaluate(async (id) => {
    const response = await fetch(`/api/backend/api/v1/events/${encodeURIComponent(id)}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Event detail returned ${response.status}.`);
    return response.json();
  }, eventId) as EventDetail;
}

async function concurrentReview(
  page: Page,
  eventId: string,
  expectedRevision: number,
  label: ReviewLabel,
  reviewer: string,
  notes: string,
): Promise<Review> {
  const result = await page.evaluate(async (input) => {
    const response = await fetch(`/api/backend/api/v1/events/${encodeURIComponent(input.eventId)}/review`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        label: input.label,
        notes: input.notes,
        reviewer: input.reviewer,
        expected_revision: input.expectedRevision,
      }),
    });
    return { body: await response.json(), status: response.status };
  }, { eventId, expectedRevision, label, reviewer, notes });
  if (result.status !== 200) throw new Error(`Concurrent review returned ${result.status}.`);
  return result.body as Review;
}

async function assertFullInspectorIdentifiers(page: Page, detail: EventDetail) {
  const sha256 = detail.recording.video?.sha256;
  if (!sha256) throw new Error("Reviewer confirmation requires attached video evidence.");
  const identifierState = await page.locator(".full-identifier").evaluateAll((elements) => elements.map((element) => ({
    selectable: getComputedStyle(element).userSelect === "text",
    text: element.textContent?.trim(),
    visible: element.getBoundingClientRect().width > 0 && element.getBoundingClientRect().height > 0,
  })));
  for (const value of [detail.event.event_id, detail.recording.recording_id, detail.event.run_id, sha256]) {
    const rendered = identifierState.find((entry) => entry.text === value);
    if (!rendered?.visible) throw new Error(`Full identifier ${value} is not visibly rendered.`);
    if (!rendered.selectable) throw new Error(`Full identifier ${value} is not selectable.`);
  }
}

async function assertMobileWaveform(page: Page) {
  await expect(page.locator(".chart-scroll-cue")).toBeVisible();
  const state = await page.locator(".chart-wrap").evaluate((element) => {
    const axis = element.querySelector(".axis-label");
    return {
      bodyContained: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      fontSize: axis ? Number.parseFloat(getComputedStyle(axis).fontSize) : 0,
      hasImmediateTable: element.nextElementSibling?.matches("details.data-table-disclosure") ?? false,
      scrollable: element.scrollWidth > element.clientWidth && element.scrollWidth >= 760,
    };
  });
  if (!state.scrollable) throw new Error("Mobile waveform is not horizontally scrollable at the required width.");
  if (!state.bodyContained) throw new Error("Waveform overflow escaped into the page body.");
  if (!state.hasImmediateTable) throw new Error("Accessible waveform table is not immediately below the chart.");
  if (state.fontSize < 16) throw new Error(`Mobile waveform labels render at ${state.fontSize}px.`);
}

type ConflictDraft = { label: ReviewLabel; notes: string; reviewer: string };

async function forceVisibleConflict(page: Page, eventId: string, base: Review, draft: ConflictDraft): Promise<Review> {
  await page.getByLabel("Observation label").selectOption(draft.label);
  await page.getByLabel("Reviewer").fill(draft.reviewer);
  await page.getByLabel(/Notes/).fill(draft.notes);
  const server = await concurrentReview(
    page,
    eventId,
    base.revision,
    "non_feeding",
    "Server-side confirmation actor",
    "Latest server review visible during reviewer confirmation.",
  );
  const conflictPromise = page.waitForResponse(
    (response) => response.url().endsWith("/review") && response.request().method() === "PUT" && response.status() === 409,
  );
  await page.getByRole("button", { name: "Save review" }).click();
  await conflictPromise;
  const alert = page.locator(".conflict-message");
  await expect(alert).toBeVisible();
  await expect(alert.getByText("Latest server review", { exact: true })).toBeVisible();
  await expect(alert.getByText(String(server.revision), { exact: true })).toBeVisible();
  await expect(alert.getByText("Non-feeding observation", { exact: true })).toBeVisible();
  await expect(alert.getByText("non_feeding", { exact: true })).toBeVisible();
  await expect(alert.getByText(server.reviewer, { exact: true })).toBeVisible();
  await expect(alert.getByText(server.notes, { exact: true })).toBeVisible();
  await expect(alert.getByText(server.updated_at, { exact: true })).toBeVisible();
  await expect(alert.getByText("Preserved draft", { exact: true })).toBeVisible();
  await expect(alert.getByText("Uncertain", { exact: true })).toBeVisible();
  await expect(alert.getByText("uncertain", { exact: true })).toBeVisible();
  await expect(alert.getByText(draft.reviewer, { exact: true })).toBeVisible();
  await expect(alert.getByText(draft.notes, { exact: true })).toBeVisible();
  await expect(page.getByLabel("Reviewer")).toHaveValue(draft.reviewer);
  await expect(page.getByLabel(/Notes/)).toHaveValue(draft.notes);
  return server;
}

async function reviewerConfirmation(page: Page, state: QaState): Promise<{ screenshots: string[]; state: QaState }> {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await selectRecordingEvent(page, state.recordingId, state.eventId);
  const detail = await fetchEventDetail(page, state.eventId);
  await assertFullInspectorIdentifiers(page, detail);

  const screenshotNames = [
    `aeolus-${round}-desktop.png`,
    `aeolus-${round}-mobile.png`,
    `aeolus-${round}-conflict-desktop.png`,
    `aeolus-${round}-conflict-mobile.png`,
  ];
  await page.screenshot({ path: resolve(artifacts, screenshotNames[0]), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await assertMobileWaveform(page);
  await page.screenshot({ path: resolve(artifacts, screenshotNames[1]), fullPage: true });

  await page.setViewportSize({ width: 1600, height: 1000 });
  const base = detail.event.review;
  if (!base) throw new Error("Reviewer confirmation requires an existing review.");
  const draft: ConflictDraft = {
    label: "uncertain",
    reviewer: "Preserved reviewer confirmation draft",
    notes: "This reviewer-confirmation draft must remain visible through repeated stale revisions.",
  };
  const firstServer = await forceVisibleConflict(page, state.eventId, base, draft);
  await page.screenshot({ path: resolve(artifacts, screenshotNames[2]), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(artifacts, screenshotNames[3]), fullPage: true });

  const secondServer = await concurrentReview(
    page,
    state.eventId,
    firstServer.revision,
    "non_feeding",
    "Second server-side confirmation actor",
    "Second concurrent server review used to recheck stale overwrite protection.",
  );
  const repeatedConflict = page.waitForResponse(
    (response) => response.url().endsWith("/review") && response.request().method() === "PUT" && response.status() === 409,
  );
  await page.getByRole("button", { name: `Save my draft over revision ${firstServer.revision}` }).click();
  await repeatedConflict;
  await expect(page.getByRole("button", { name: `Save my draft over revision ${secondServer.revision}` })).toBeVisible();
  await expect(page.getByText(secondServer.reviewer, { exact: true })).toBeVisible();
  await expect(page.getByText(secondServer.notes, { exact: true })).toBeVisible();
  await expect(page.getByLabel("Reviewer")).toHaveValue(draft.reviewer);
  await expect(page.getByLabel(/Notes/)).toHaveValue(draft.notes);

  const overwritePromise = page.waitForResponse(
    (response) => response.url().endsWith("/review") && response.request().method() === "PUT" && response.status() === 200,
  );
  await page.getByRole("button", { name: `Save my draft over revision ${secondServer.revision}` }).click();
  const overwriteResponse = await overwritePromise;
  const persisted = (await overwriteResponse.json()) as Review;
  if (persisted.revision !== secondServer.revision + 1 || persisted.notes !== draft.notes || persisted.reviewer !== draft.reviewer) {
    throw new Error("Explicit overwrite did not persist the preserved draft at a new revision.");
  }
  return {
    screenshots: screenshotNames.map((name) => `qa/artifacts/${name}`),
    state: { ...state, reviewRevision: persisted.revision },
  };
}

async function capture(page: Page, state: QaState) {
  await selectRecordingEvent(page, state.recordingId, state.eventId);
  await page.screenshot({ path: resolve(artifacts, `aeolus-${round}-desktop.png`), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(artifacts, `aeolus-${round}-mobile.png`), fullPage: true });
}

mkdirSync(artifacts, { recursive: true });
let browser: Browser | null = null;
let tempRoot: string | null = null;
try {
  const token = accessKey();
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();
  let state: QaState;
  let screenshots: string[];

  if (round === "inspection") {
    await unlock(page, token, true);
    await submitDemo(page);
    tempRoot = mkdtempSync(join(tmpdir(), "aeolus-ui-qa-"));
    const recordingFixture = createRecordingFixture(tempRoot);
    const videoFixture = createVideoFixture(tempRoot);
    await importRecording(page, recordingFixture);
    const eventId = await selectRecordingEvent(page, recordingFixture.recordingId);
    if (!eventId) throw new Error("The imported recording did not expose an event ID in the inspector.");
    const initialReview = await saveInitialReview(page);
    await verifyReviewAfterReload(page, recordingFixture.recordingId, eventId, initialReview);
    const finalReview = await proveRevisionConflict(page, eventId, initialReview);
    await attachVideo(page, videoFixture);
    await proveLogoutAndRecovery(page, token);
    await proveSimulatedNetworkRecovery(page);
    state = { eventId, recordingId: recordingFixture.recordingId, reviewRevision: finalReview.revision };
    writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
    await capture(page, state);
    screenshots = [
      `qa/artifacts/aeolus-${round}-desktop.png`,
      `qa/artifacts/aeolus-${round}-mobile.png`,
    ];
  } else if (round === "reviewer-confirmation") {
    state = JSON.parse(readFileSync(statePath, "utf8")) as QaState;
    await unlock(page, token, false);
    const confirmation = await reviewerConfirmation(page, state);
    state = confirmation.state;
    screenshots = confirmation.screenshots;
    writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  } else {
    state = JSON.parse(readFileSync(statePath, "utf8")) as QaState;
    await unlock(page, token, false);
    await capture(page, state);
    screenshots = [
      `qa/artifacts/aeolus-${round}-desktop.png`,
      `qa/artifacts/aeolus-${round}-mobile.png`,
    ];
  }

  writeFileSync(
    resolve(artifacts, `aeolus-${round}-results.json`),
    `${JSON.stringify({
      round,
      recordingId: state.recordingId,
      eventId: state.eventId,
      reviewRevision: state.reviewRevision,
      networkFailureTest: round === "inspection"
        ? "simulated with a Playwright route abort; not a field-outage claim"
        : "not repeated in this confirmation batch",
      screenshots,
    }, null, 2)}\n`,
    "utf8",
  );
  await context.close();
} finally {
  if (tempRoot) rmSync(tempRoot, { force: true, recursive: true });
  await browser?.close();
}
