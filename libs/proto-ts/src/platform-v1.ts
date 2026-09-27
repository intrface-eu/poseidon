// Additive local platform API. Recording/candidate v1 contracts remain unchanged.
export type Role = "viewer" | "reviewer" | "admin" | "device" | "operator";
export type AuthMode = "local_development_key" | "scoped_token";
export type SourceKind = "synthetic" | "bench" | "field";
export type Identity = { subject: string; role: Role; site_ids: string[]; device_id: string | null; auth_mode: AuthMode };
export type ObservationLabel = "feeding_observed" | "no_feeding_observed" | "uncertain" | "not_visible";
export type ReviewContext = { protocol_id: string | null; evidence_refs: string[]; visibility: "clear" | "limited" | "not_visible" | "unknown"; sync_uncertainty_s: number | null; reviewed_coverage: boolean };
export type ObservationInput = { id: string; start_s: number; end_s: number; label: ObservationLabel; notes: string; observer: string; expected_revision: number; review_context?: ReviewContext };
export type Observation = ObservationInput & {
  recording_id: string; revision: number; actor_subject: string; auth_mode: AuthMode;
  created_at: string; updated_at: string;
  provenance: { recording_sha256: string; source_kind: SourceKind };
};
export type DeviceInput = { id: string; site_id: string; label: string; kind: "reef" | "aquilon" | "hub"; hardware_revision: string; source_kind: SourceKind };
export type PrincipalInput = { subject: string; role: Role; site_ids: string[]; device_id: string | null };

export type Device = DeviceInput & { created_at: string; revoked_at: string | null };
export type Principal = PrincipalInput & { id: string; created_at: string; updated_at: string; revoked_at: string | null };
export type Credential = { principal: Principal; token: string };
export type ClockQuality = { status: "unknown" | "operator_declared" | "synchronized" | "holdover"; method: "unknown" | "operator_offset" | "ntp" | "gnss" | "shared_clock" | "measured_reference"; uncertainty_ms: number | null; offset_ms: number | null; reference: string | null };
export type Provenance = { source_kind: SourceKind; source_id: string; transport: "local" | "aquilon" | "import" };
export type ClockRelation = { source_domain: string; reference_domain: string; source_anchor_s: number; reference_anchor_s: number; drift_ppm: number; anchor_uncertainty_s: number; drift_uncertainty_ppm: number; method: "operator_declared" | "measured_reference" | "shared_clock"; evidence_ref: string | null };
export type AcquisitionSession = { schema_version: "poseidon.acquisition-session.v1"; id: string; site_id: string; device_id: string | null; started_at: string | null; ended_at: string | null; clock_quality: ClockQuality; provenance: Provenance; operator: string; notes: string; clock_relation?: ClockRelation | null };
export type AquilonMappingInput = { dev_eui: string; calibration_refs: { code: number; sensor_kind: "temperature" | "salinity" | "dissolved_oxygen"; calibration_id: string }[] };
export type RadioProvenance = { dev_eui: string; uptime_s: number; power_mode: "normal" | "conserve" | "critical"; clock_claim: "unsynchronized" | "rtc" | "network"; observed_at_unix_s: number | null; network_received_at: string | null; frame_sha256: string; calibration_code: number | null };
export type Measurement = { name: string; value: number | null; unit: string; quality: "uncalibrated" | "calibrated" | "invalid"; calibration_id: string | null };
export type TelemetryEnvelope = { schema_version: "poseidon.telemetry.v1"; device_id: string; site_id: string; boot_id: string; sequence: number; observed_at: string | null; delivery_age_s: number; clock_quality: ClockQuality; provenance: Provenance; measurements: Measurement[]; radio?: RadioProvenance };
export type Telemetry = { id: string; envelope: TelemetryEnvelope; received_at: string; actor_subject: string; duplicate: boolean };
export type AuditEntry = { id: string; action: string; actor_subject: string; auth_mode: AuthMode; site_id: string | null; device_id: string | null; resource_id: string | null; created_at: string; details: Record<string, unknown> };

export function canReview(identity: Identity | null): boolean {
  return identity?.role === "reviewer" || identity?.role === "admin";
}
export function canAdmin(identity: Identity | null): boolean { return identity?.role === "admin"; }
export function canImport(identity: Identity | null): boolean {
  return identity?.auth_mode === "local_development_key" && identity.role === "admin";
}
export function isIdentity(value: unknown): value is Identity {
  if (!value || typeof value !== "object") return false;
  const row = value as Record<string, unknown>;
  return typeof row.subject === "string" && ["viewer", "reviewer", "admin", "device", "operator"].includes(String(row.role))
    && ["local_development_key", "scoped_token"].includes(String(row.auth_mode))
    && Array.isArray(row.site_ids) && row.site_ids.every((site) => typeof site === "string")
    && (row.device_id === null || typeof row.device_id === "string")
    && (row.role !== "device" || (typeof row.device_id === "string" && row.site_ids.length === 1));
}
export function validateObservation(input: ObservationInput, duration: number): string | null {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(input.id)) return "Use a safe observation ID of at most 128 characters.";
  if (!Number.isFinite(input.start_s) || !Number.isFinite(input.end_s) || input.start_s < 0 || input.start_s >= input.end_s || input.end_s > duration) return `Enter an interval within 0–${duration} seconds, with end after start.`;
  if (!["feeding_observed", "no_feeding_observed", "uncertain", "not_visible"].includes(input.label)) return "Choose an observation label.";
  if (!input.observer.trim() || input.observer.length > 80) return "Enter a declared observer name of at most 80 characters.";
  if (input.notes.length > 2000) return "Limit notes to 2000 characters.";
  if (input.label === "feeding_observed" && !input.notes.trim()) return "Describe the basis for the feeding observation in notes.";
  if (!Number.isSafeInteger(input.expected_revision) || input.expected_revision < 0) return "The revision is invalid. Reload the server record.";
  const context = input.review_context;
  if (context && context.sync_uncertainty_s !== null && (!Number.isFinite(context.sync_uncertainty_s) || context.sync_uncertainty_s < 0)) return "Sync uncertainty must be a finite nonnegative number of seconds, or unknown.";
  if (context && context.evidence_refs.length > 32) return "Use at most 32 evidence references.";
  return null;
}

/** Boot counters are uint64 decimal text, never IEEE-754 numbers. */
export function isBootId(value: unknown): value is string {
  return typeof value === "string" && /^[1-9][0-9]{0,19}$/.test(value) && BigInt(value) <= 18446744073709551615n;
}
export function parseBoundedObject(text: string, maximumBytes = 64 * 1024): Record<string, unknown> {
  if (new TextEncoder().encode(text).byteLength > maximumBytes) throw new Error(`JSON exceeds ${maximumBytes} bytes.`);
  const value: unknown = JSON.parse(text);
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Enter one JSON object.");
  return value as Record<string, unknown>;
}
