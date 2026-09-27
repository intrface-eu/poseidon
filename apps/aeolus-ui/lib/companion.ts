import { ApiError } from "./client-api";
import {
  COMPANION_SCHEMA_VERSION, COMPANION_UPLOAD_ROLES, COMPANION_DOCUMENT_ROLES,
  COMPANION_PART_LIMITS, COMPANION_MAX_BYTES, COMPANION_MAX_REQUEST_BYTES,
  type AcquisitionCompanion, type CompanionDocument, type CompanionUploadRole,
} from "../../../libs/proto-ts/src/companion-v1";

export * from "../../../libs/proto-ts/src/companion-v1";

export const COMPANION_FILE_LABELS: Record<CompanionUploadRole, string> = {
  wav: "Selected segment WAV", manifest: "Recording manifest", binding: "Segment binding",
  source_receipt: "Selected source receipt", source_header: "Source session header",
  source_final: "Final source snapshot", export_receipt: "Committed export receipt",
};
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const SHA256 = /^[a-f0-9]{64}$/;
const object = (value: unknown): value is Record<string, unknown> => Boolean(value && typeof value === "object" && !Array.isArray(value));
export const safeCompanionId = (value: string) => SAFE_ID.test(value);
export const flatCompanionName = (value: string) => value.length > 0 && value.length <= 255 && !value.includes("/") && !value.includes("\\") && [...value].every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127) && value !== "." && value !== "..";
export const evidenceText = (value: unknown): string => value === null || value === undefined ? "Not supplied" : typeof value === "string" ? value : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);

/** Mechanical transport preflight only; Acquisition's reader checks the export semantics. */
export function validateCompanionSelection(files: Partial<Record<CompanionUploadRole, { name: string; size: number }>>, sessionId: string): string | null {
  if (!safeCompanionId(sessionId)) return "Select an existing authorized platform session.";
  if (Object.keys(files).some((role) => !COMPANION_UPLOAD_ROLES.includes(role as CompanionUploadRole))) return "Use exactly the seven file roles. Archives and extra roles are not accepted.";
  let companionBytes = 0;
  let payloadBytes = 0;
  const names = new Set<string>();
  for (const role of COMPANION_UPLOAD_ROLES) {
    const file = files[role];
    if (!file || !Number.isSafeInteger(file.size) || file.size <= 0) return `Choose the original ${COMPANION_FILE_LABELS[role].toLowerCase()} file.`;
    if (!flatCompanionName(file.name)) return "Files must keep their original flat export basenames, not paths.";
    if (names.has(file.name)) return "Each role must use a distinct original export file; a file was selected twice.";
    names.add(file.name);
    if (file.size > COMPANION_PART_LIMITS[role]) return `${COMPANION_FILE_LABELS[role]} exceeds its ${COMPANION_PART_LIMITS[role]}-byte local limit.`;
    payloadBytes += file.size;
    if (COMPANION_DOCUMENT_ROLES.includes(role as (typeof COMPANION_DOCUMENT_ROLES)[number])) companionBytes += file.size;
  }
  if (companionBytes > COMPANION_MAX_BYTES) return `The five companion JSON files exceed ${COMPANION_MAX_BYTES} bytes together. They cannot be truncated.`;
  if (payloadBytes > COMPANION_MAX_REQUEST_BYTES - 262144) return "The selected files exceed the request payload budget.";
  return null;
}

export function companionFormData(files: Partial<Record<CompanionUploadRole, File>>): FormData {
  const body = new FormData();
  for (const role of COMPANION_UPLOAD_ROLES) {
    const file = files[role];
    if (!(file instanceof File)) throw new Error(`Missing file role: ${role}`);
    body.append(role, file, file.name);
  }
  return body;
}

/** Rendering-envelope guard, not a scientific validator or a replacement for raw bytes. */
export function isCompanionEnvelope(value: unknown, recordingId: string): value is AcquisitionCompanion {
  if (!object(value) || value.schema_version !== COMPANION_SCHEMA_VERSION || value.recording_id !== recordingId) return false;
  if (value.state === "absent") return true;
  if (value.state !== "retained" || !object(value.binding) || !object(value.validation) || !object(value.job)) return false;
  if (!["queued", "running", "succeeded", "failed"].includes(String(value.job.status)) || typeof value.job.id !== "string") return false;
  if (!["platform_session_id", "capture_session_id", "source_id", "actor_subject", "auth_mode", "imported_at"].every((key) => typeof value[key] === "string")) return false;
  if (!["local_development_key", "scoped_token"].includes(String(value.auth_mode))) return false;
  if (!["source_header_sha256", "source_final_sha256", "wav_sha256", "manifest_sha256"].every((key) => typeof value[key] === "string" && SHA256.test(value[key] as string))) return false;
  if (!Number.isSafeInteger(value.selected_index) || Number(value.selected_index) < 0) return false;
  if (!Array.isArray(value.documents) || value.documents.length !== COMPANION_DOCUMENT_ROLES.length) return false;
  if (!value.documents.every((doc, index) => object(doc) && doc.role === COMPANION_DOCUMENT_ROLES[index] && typeof doc.name === "string" && flatCompanionName(doc.name) && Number.isSafeInteger(doc.bytes) && Number(doc.bytes) > 0 && Number(doc.bytes) <= COMPANION_PART_LIMITS[COMPANION_DOCUMENT_ROLES[index]] && typeof doc.sha256 === "string" && SHA256.test(doc.sha256))) return false;
  const binding = value.binding;
  if (!object(binding.source) || !Array.isArray(binding.source.channels) || !binding.source.channels.every((channel) => object(channel) && typeof channel.channel_id === "string" && typeof channel.role === "string")) return false;
  return object(binding.source.clock) && object(binding.time) && object(binding.time.epoch_declaration)
    && object(binding.mapping) && object(binding.original_receipt) && object(binding.original_receipt.record)
    && object(binding.source_accounting) && object(binding.provenance);
}

export function companionProblem(error: unknown) {
  const status = error instanceof ApiError ? error.status : 0;
  const detail = error instanceof ApiError ? error.message : "The local API did not acknowledge the request. Check the retained record or job before retrying.";
  const title = status === 401 ? "Session authorization lost" : status === 403 ? "Operation not allowed for this identity" : status === 404 ? "Context or record unavailable in this scope" : status === 413 ? "Local byte or part limit exceeded" : status === 409 ? "Identity, binding or capacity conflict" : status === 400 ? "Export package rejected" : "Request not completed";
  return { status, title, detail, authLost: status === 401 || status === 403 || status === 404 };
}

async function boundedResponseBytes(response: Response, maximum: number): Promise<Uint8Array> {
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      total += result.value.byteLength;
      if (total > maximum) {
        await reader.cancel("document transfer exceeded bound");
        throw new ApiError(502, "invalid_document_response", "The document response exceeded its local transfer bound.");
      }
      chunks.push(result.value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return bytes;
}

/** Check exact transfer bytes against catalog metadata; this does not attest source claims. */
export async function companionDownloadBlob(response: Response, document: CompanionDocument): Promise<Blob> {
  if (!response.ok) {
    let code = "document_request_failed";
    let message = `Document request returned HTTP ${response.status}.`;
    try {
      const data = JSON.parse(new TextDecoder().decode(await boundedResponseBytes(response, 16384)));
      if (typeof data?.error?.code === "string") code = data.error.code;
      if (typeof data?.error?.message === "string") message = data.error.message;
    } catch { /* Keep the safe status message; never echo a raw document. */ }
    throw new ApiError(response.status, code, message);
  }
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json") || response.headers.get("x-poseidon-document-sha256") !== document.sha256) throw new ApiError(502, "invalid_document_response", "The document response does not match the selected catalog entry.");
  const bytes = await boundedResponseBytes(response, COMPANION_PART_LIMITS[document.role]);
  if (bytes.length !== document.bytes) throw new ApiError(502, "invalid_document_response", "The document length differs from its retained catalog entry.");
  const digest = await crypto.subtle.digest("SHA-256", bytes.buffer as ArrayBuffer);
  const sha256 = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  if (sha256 !== document.sha256) throw new ApiError(502, "invalid_document_response", "The downloaded bytes do not match the retained SHA-256.");
  return new Blob([bytes.buffer as ArrayBuffer], { type: "application/json" });
}
