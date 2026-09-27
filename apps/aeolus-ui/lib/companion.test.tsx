import { describe, expect, test } from "bun:test";
import { createHash } from "node:crypto";
import { renderToStaticMarkup } from "react-dom/server";
import { CompanionImport } from "../components/CompanionImport";
import { RetainedCompanionView } from "../components/CompanionPanel";
import { ApiError } from "./client-api";
import { matchBackendRequest } from "./backend-contract";
import {
  COMPANION_SCHEMA_VERSION, COMPANION_UPLOAD_ROLES, COMPANION_DOCUMENT_ROLES,
  COMPANION_PART_LIMITS, COMPANION_MAX_REQUEST_BYTES, companionFormData,
  companionDownloadBlob, companionProblem, evidenceText, flatCompanionName,
  isCompanionEnvelope, validateCompanionSelection, type CompanionRetained,
  type CompanionDocument, type CompanionUploadRole,
} from "./companion";
import type { Identity } from "./platform";

const id = "synthetic-ui-render-recording";
const zeroHash = "0".repeat(64);
const roleNames: Record<CompanionUploadRole, string> = {
  wav: "chunk-000000.wav", manifest: "recording-000000.v1.json", binding: "binding-000000.json",
  source_receipt: "source-receipt-000000.json", source_header: "source-header.json",
  source_final: "source-final.json", export_receipt: "export.receipt.json",
};
const files = () => Object.fromEntries(COMPANION_UPLOAD_ROLES.map((role) => [role, { name: roleNames[role], size: 12 }])) as Record<CompanionUploadRole, { name: string; size: number }>;

// Render-only props, intentionally not a validated export package or E2E fixture.
// Real positive acceptance must use Acquisition's actual exported files/reader/API.
function renderFixture(status: CompanionRetained["job"]["status"] = "succeeded"): CompanionRetained {
  const reference = { path: "synthetic-unit.json", bytes: 12, sha256: zeroHash };
  return {
    schema_version: COMPANION_SCHEMA_VERSION, state: "retained", recording_id: id,
    platform_session_id: "synthetic-manual-context", capture_session_id: "synthetic-source-session", source_id: "synthetic-source", selected_index: 0,
    source_header_sha256: zeroHash, source_final_sha256: zeroHash, wav_sha256: zeroHash, manifest_sha256: zeroHash,
    imported_at: "2026-01-01T00:00:00Z", actor_subject: "synthetic-authenticated-importer", auth_mode: "scoped_token",
    job: { id: "synthetic-job", status },
    documents: COMPANION_DOCUMENT_ROLES.map((role) => ({ role, name: roleNames[role], bytes: 12, sha256: zeroHash })),
    validation: { schema: "synthetic-ui-render-only", verification: { original_input_bytes_verified: false, full_original_session_bytes_verified: false, acquisition_completeness_verified: false } },
    binding: {
      schema: "poseidon.legacy-segment-export.provisional.v1.binding", session_id: "synthetic-source-session", source_id: "synthetic-source",
      mapping: { recording_id: id, segment_index: 0, site_id: "synthetic-site", zone_id: "synthetic-zone", device_id: "synthetic-device" },
      source: {
        source_id: "synthetic-source", media: "pcm16-wav", provenance: "synthetic", sample_rate_hz: 8000, source_origin_s: 0,
        channels: [{ channel_id: "synthetic-left", role: "synthetic first channel" }, { channel_id: "synthetic-right", role: "synthetic second channel" }],
        origin: '<img src="x" onerror="synthetic-only">', input_sha256: null,
        clock: { source_domain: "source_seconds", reference_domain: "reference_seconds", reference_epoch: "synthetic-epoch", source_anchor_s: 0, reference_anchor_s: 0.25, drift_ppm: 20, anchor_uncertainty_s: 0.01, drift_uncertainty_ppm: 2, method: "operator_declared", evidence_ref: "javascript:syntheticOnly()" },
      },
      original_header: { path: "synthetic-header.json", exported_copy: reference },
      original_final: { path: "synthetic-final.json", exported_copy: reference },
      original_receipt: { path: "synthetic-receipt.json", exported_copy: reference, record: { schema: "poseidon.acquisition-session.provisional.v1.chunk", index: 0, header_sha256: zeroHash, previous_receipt_sha256: null, source_id: "synthetic-source", path: "chunk-000000.wav", sha256: zeroHash, bytes: 12, unit_start: 2400, units: 1600, source_start_s: 0.3, source_end_s: 0.5, reference_start_s: 0.550006, reference_end_s: 0.750010, start_uncertainty_s: 0.01, end_uncertainty_s: 0.01, missing_units: 800, dropped_units: 800, unexplained_missing_units: 0, gap_source_s: 0.09999999999999998, gap_reason: "Synthetic omitted-frame reason" } },
      original_segment: reference, exported_wav: reference, recording_manifest: reference,
      bytes_transformed: false, copy_operation: "Synthetic render fixture only; no export-validation evidence",
      time: { epoch_declaration: { source_id: "synthetic-source", reference_domain: "reference_seconds", reference_epoch: "synthetic-epoch", epoch_utc: "2026-01-01T00:00:00Z", uncertainty_s: 0.005, declared_by: "synthetic-declarant", evidence_ref: "javascript:syntheticOnly()" }, epoch_declaration_verified: false, epoch_relation: "Synthetic declared relation", started_at: "2026-01-01T00:00:00.550006Z", reference_ended_at: "2026-01-01T00:00:00.750010Z", nominal_wav_ended_at: "2026-01-01T00:00:00.750006Z", started_at_rounding_error_s: "0.000000", reference_end_rounding_error_s: "0.00000", combined_start_uncertainty_s: "0.0150006", combined_end_uncertainty_s: "0.015001", uncertainty_combination: "sum of declared bounds; unverified", clock_relation_verified: false, v1_candidate_offsets: "segment-local nominal WAV seconds", candidate_reference_mapping: "INERT synthetic mapping expression", nominal_duration_s: "0.200000", reference_duration_s: "0.200004000", resampled_for_clock_drift: false },
      provenance: { original_provenance: "synthetic", file_origin_declaration: null, origin_verified: false, authorization_verified: false },
      acquisition_state: "finalized", capture_extent: "stored_segments_only; trailing_extent_not_attested", source_accounting: { stored_units: 3200, missing_units: 800, dropped_units: 800, gap_source_s: 0.09999999999999998 }, acquisition_completeness_verified: false, calibration_status: "uncalibrated", hardware_verified: false, authorization_verified: false, metadata_loss_in_v1: ["synthetic render fixture"],
    },
  };
}
const match = (method: string, path: string, query = "") => matchBackendRequest(method, path.split("/").filter(Boolean), new URLSearchParams(query));

describe("companion transport preflight, not scientific validation", () => {
  test("allows seven mechanically valid files and keeps every fixed part limit", () => {
    const selected = files();
    expect(validateCompanionSelection(selected, "synthetic-session")).toBeNull();
    for (const role of COMPANION_UPLOAD_ROLES) {
      expect(validateCompanionSelection({ ...selected, [role]: { ...selected[role], size: COMPANION_PART_LIMITS[role] } }, "synthetic-session")).toBeNull();
      expect(validateCompanionSelection({ ...selected, [role]: { ...selected[role], size: COMPANION_PART_LIMITS[role] + 1 } }, "synthetic-session")).not.toBeNull();
    }
  });
  test("rejects missing/extra/empty parts, duplicate names and unsafe context/path text", () => {
    const selected = files(); delete (selected as Partial<typeof selected>).binding;
    expect(validateCompanionSelection(selected, "synthetic-session")).not.toBeNull();
    expect(validateCompanionSelection({ ...files(), extra: { name: "extra.json", size: 1 } } as typeof selected, "synthetic-session")).not.toBeNull();
    expect(validateCompanionSelection({ ...files(), binding: { name: roleNames.manifest, size: 1 } }, "synthetic-session")).not.toBeNull();
    expect(validateCompanionSelection(files(), "../session")).not.toBeNull();
    for (const name of ["../a.json", "a/b", "a\\b", ".", "..", "x" + String.fromCharCode(13)]) expect(flatCompanionName(name)).toBe(false);
    expect(validateCompanionSelection({ ...files(), source_final: { name: "source-final.json", size: 0 } }, "synthetic-session")).not.toBeNull();
  });
  test("multipart builder emits only seven File values and preserves their bytes/names", async () => {
    const selected = Object.fromEntries(COMPANION_UPLOAD_ROLES.map((role) => [role, new File([new Uint8Array([255, 254, 123, 0, 125, 0])], roleNames[role])])) as Record<CompanionUploadRole, File>;
    const form = companionFormData(selected);
    expect([...form.keys()]).toEqual([...COMPANION_UPLOAD_ROLES]);
    for (const role of COMPANION_UPLOAD_ROLES) {
      const value = form.get(role); expect(value instanceof File).toBe(true);
      expect((value as File).name).toBe(roleNames[role]);
      expect([...new Uint8Array(await (value as File).arrayBuffer())]).toEqual([255, 254, 123, 0, 125, 0]);
    }
    expect(form.has("session_id")).toBe(false);
  });
  test("proxy exposes only the fixed session upload and five scoped document reads", () => {
    expect(match("POST", "/api/v1/acquisition-sessions/synthetic-session/recordings")?.bodyLimit).toBe(COMPANION_MAX_REQUEST_BYTES);
    expect(match("GET", `/api/v1/recordings/${id}/acquisition-companion`)).not.toBeNull();
    for (const role of COMPANION_DOCUMENT_ROLES) expect(match("GET", `/api/v1/recordings/${id}/acquisition-companion/documents/${role}`)).not.toBeNull();
    for (const role of ["wav", "manifest", "source.wav", "source-final.json", "unknown", ".."]) expect(match("GET", `/api/v1/recordings/${id}/acquisition-companion/documents/${role}`)).toBeNull();
    expect(match("POST", "/api/v1/acquisition-sessions/synthetic-session/recordings", "url=https://example.com")).toBeNull();
    expect(match("PUT", `/api/v1/recordings/${id}/acquisition-companion`)).toBeNull();
    expect(match("GET", `/api/v1/recordings/${id}/acquisition-companion`, "role=binding")).toBeNull();
  });
});

describe("companion rendering boundaries", () => {
  test("guards requested identity and rendering shape without validating source science", () => {
    const value = renderFixture();
    expect(isCompanionEnvelope(value, id)).toBe(true);
    expect(isCompanionEnvelope(value, "another-record")).toBe(false);
    expect(isCompanionEnvelope({ schema_version: COMPANION_SCHEMA_VERSION, state: "absent", recording_id: id }, id)).toBe(true);
    expect(isCompanionEnvelope({ ...value, documents: [...value.documents].reverse() }, id)).toBe(false);
    expect(isCompanionEnvelope({ ...value, auth_mode: "physically_verified" }, id)).toBe(false);
    expect(isCompanionEnvelope({ ...value, binding: {} }, id)).toBe(false);
  });
  test("retains exact decimal strings, channel order, both namespaces and unverified limits", () => {
    const html = renderToStaticMarkup(<RetainedCompanionView value={renderFixture()} onDownloadError={() => {}} />);
    for (const expected of ["synthetic-manual-context", "synthetic-source-session", "synthetic-authenticated-importer", "0.200004000", "0.0150006", "0.09999999999999998", "Stored segments only", "trailing capture extent", "Acquisition completeness verified", "false"]) expect(html).toContain(expected);
    expect(html.indexOf("synthetic-left")).toBeLessThan(html.indexOf("synthetic-right"));
    expect(html).toContain("Nominal duration (s)"); expect(html).toContain("Reference duration (s)");
    for (const role of COMPANION_DOCUMENT_ROLES) expect(html).toContain(`Download ${role}`);
    expect(evidenceText(null)).toBe("Not supplied"); expect(evidenceText(false)).toBe("false"); expect(evidenceText(0)).toBe("0");
  });
  test("escapes declarations and never creates links from origin/evidence text", () => {
    const html = renderToStaticMarkup(<RetainedCompanionView value={renderFixture()} onDownloadError={() => {}} />);
    expect(html).toContain("&lt;img"); expect(html).not.toContain('<img src="x"');
    expect(html).toContain("javascript:syntheticOnly()"); expect(html).not.toContain('href="javascript:');
  });
  test("pending and failed replay retain inspection controls without claiming availability", () => {
    const pending = renderToStaticMarkup(<RetainedCompanionView value={renderFixture("queued")} onDownloadError={() => {}} />);
    expect(pending).toContain("Companions are retained while replay is pending"); expect(pending).toContain("Download source_final");
    const failed = renderToStaticMarkup(<RetainedCompanionView value={renderFixture("failed")} onDownloadError={() => {}} />);
    expect(failed).toContain("Replay failed"); expect(failed).toContain("No candidate availability is claimed"); expect(failed).toContain("Download source_final");
  });
  test("non-admin form keeps seven explicit disabled file roles and no scalar scope part", () => {
    const identity: Identity = { subject: "synthetic-viewer", role: "viewer", site_ids: ["synthetic-site"], device_id: null, auth_mode: "scoped_token" };
    const html = renderToStaticMarkup(<CompanionImport identity={identity} onSubmitted={() => {}} onDirtyChange={() => {}} />);
    expect(html).toContain("Admin upload only"); expect(html).toContain("fieldset disabled");
    expect((html.match(/type="file"/g) ?? []).length).toBe(7);
    expect(html).not.toContain('name="session_id"'); expect(html).not.toContain('name="platform_session_id"');
  });
  test("auth loss, capacity, malformed packages and byte limits have distinct messages", () => {
    expect(companionProblem(new ApiError(401, "invalid_key", "Synthetic revoked credential")).authLost).toBe(true);
    expect(companionProblem(new ApiError(404, "not_found", "Not found")).title).toContain("scope");
    expect(companionProblem(new ApiError(409, "quota", "Synthetic quota reached")).title).toContain("capacity");
    expect(companionProblem(new ApiError(413, "too_large", "Synthetic too large")).title).toContain("limit");
    expect(companionProblem(new ApiError(400, "invalid_export", "Synthetic invalid package")).title).toContain("rejected");
  });
});

describe("exact opaque companion document transfer", () => {
  const bytes = new Uint8Array([255, 254, 123, 0, 125, 0, 10, 0]); // UTF-16 BOM + {} + newline, transfer-unit fixture only.
  const hash = createHash("sha256").update(bytes).digest("hex");
  const document: CompanionDocument = { role: "source_final", name: "source-final.json", bytes: bytes.length, sha256: hash };
  const headers = { "content-type": "application/json", "x-poseidon-document-sha256": hash };
  test("preserves original non-UTF8 bytes rather than parsing/re-encoding JSON", async () => {
    const blob = await companionDownloadBlob(new Response(bytes, { headers }), document);
    expect([...new Uint8Array(await blob.arrayBuffer())]).toEqual([...bytes]);
  });
  test("rejects mismatched digest header, byte length and content hash", async () => {
    await expect(companionDownloadBlob(new Response(bytes, { headers: { ...headers, "x-poseidon-document-sha256": zeroHash } }), document)).rejects.toThrow();
    await expect(companionDownloadBlob(new Response(bytes.subarray(0, 6), { headers }), document)).rejects.toThrow();
    await expect(companionDownloadBlob(new Response(new Uint8Array(bytes.length), { headers }), document)).rejects.toThrow();
  });
  test("retains HTTP authorization failure without reflecting raw document content", async () => {
    const response = new Response(JSON.stringify({ error: { code: "invalid_access_key", message: "Synthetic revoked session" } }), { status: 401, headers: { "content-type": "application/json" } });
    try { await companionDownloadBlob(response, document); throw new Error("Expected rejection"); }
    catch (error) { expect(error instanceof ApiError).toBe(true); expect((error as ApiError).status).toBe(401); }
  });
});
