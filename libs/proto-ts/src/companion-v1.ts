// Transport and inspection types only. Acquisition's pure reader validates science.
export const COMPANION_SCHEMA_VERSION = "poseidon.recording-acquisition-companion.v1" as const;
export const COMPANION_UPLOAD_ROLES = ["wav", "manifest", "binding", "source_receipt", "source_header", "source_final", "export_receipt"] as const;
export const COMPANION_DOCUMENT_ROLES = ["binding", "source_receipt", "source_header", "source_final", "export_receipt"] as const;
export type CompanionUploadRole = (typeof COMPANION_UPLOAD_ROLES)[number];
export type CompanionDocumentRole = (typeof COMPANION_DOCUMENT_ROLES)[number];
export const COMPANION_PART_LIMITS: Readonly<Record<CompanionUploadRole, number>> = {
  wav: 8388608, manifest: 16384, binding: 262144, source_receipt: 16384,
  source_header: 1048576, source_final: 2097152, export_receipt: 65536,
};
export const COMPANION_MAX_BYTES = 4194304;
export const COMPANION_MAX_REQUEST_BYTES = 12861440;
export const COMPANION_MAX_ADMISSIONS = 2;
export const COMPANION_MAX_QUEUE_SLOTS = 32;
export const COMPANION_MAX_RETAINED_BYTES = 268435456;

export type CompanionAuthMode = "local_development_key" | "scoped_token";
export type CompanionJobStatus = "queued" | "running" | "succeeded" | "failed";
export interface CompanionDocument {
  role: CompanionDocumentRole;
  name: string;
  bytes: number;
  sha256: string;
}
export interface LegacyFileReference { path: string; bytes: number; sha256: string }
export interface LegacySourceClock {
  source_domain: string;
  reference_domain: string;
  reference_epoch: string;
  source_anchor_s: number;
  reference_anchor_s: number;
  drift_ppm: number;
  anchor_uncertainty_s: number;
  drift_uncertainty_ppm: number;
  method: "operator_declared" | "measured_reference" | "shared_clock";
  evidence_ref: string | null;
}
export interface LegacyExportSource {
  source_id: string;
  media: "pcm16-wav";
  provenance: "synthetic" | "file";
  channels: Array<{ channel_id: string; role: string }>;
  clock: LegacySourceClock;
  sample_rate_hz: number;
  source_origin_s: number;
  origin: string;
  input_sha256: string | null;
}
export interface LegacySourceReceipt {
  schema: "poseidon.acquisition-session.provisional.v1.chunk";
  index: number;
  header_sha256: string;
  previous_receipt_sha256: string | null;
  source_id: string;
  path: string;
  sha256: string;
  bytes: number;
  unit_start: number;
  units: number;
  source_start_s: number;
  source_end_s: number;
  reference_start_s: number;
  reference_end_s: number;
  start_uncertainty_s: number;
  end_uncertainty_s: number;
  missing_units: number;
  dropped_units: number;
  unexplained_missing_units: number;
  gap_source_s: number;
  gap_reason: string;
}
export interface LegacyEpochDeclaration {
  source_id: string;
  reference_domain: string;
  reference_epoch: string;
  epoch_utc: string;
  uncertainty_s: number;
  declared_by: string;
  evidence_ref: string;
}
export interface LegacyExportTime {
  epoch_declaration: LegacyEpochDeclaration;
  epoch_declaration_verified: false;
  epoch_relation: string;
  started_at: string;
  reference_ended_at: string;
  nominal_wav_ended_at: string;
  started_at_rounding_error_s: string;
  reference_end_rounding_error_s: string;
  combined_start_uncertainty_s: string;
  combined_end_uncertainty_s: string;
  uncertainty_combination: string;
  clock_relation_verified: false;
  v1_candidate_offsets: string;
  candidate_reference_mapping: string;
  nominal_duration_s: string;
  reference_duration_s: string;
  resampled_for_clock_drift: false;
}
export interface LegacyExportBinding {
  schema: "poseidon.legacy-segment-export.provisional.v1.binding";
  session_id: string;
  source_id: string;
  mapping: { segment_index: number; recording_id: string; site_id: string; zone_id: string; device_id: string };
  source: LegacyExportSource;
  original_header: { path: string; exported_copy: LegacyFileReference };
  original_final: { path: string; exported_copy: LegacyFileReference };
  original_receipt: { path: string; exported_copy: LegacyFileReference; record: LegacySourceReceipt };
  original_segment: LegacyFileReference;
  exported_wav: LegacyFileReference;
  recording_manifest: LegacyFileReference;
  bytes_transformed: false;
  copy_operation: string;
  time: LegacyExportTime;
  provenance: {
    original_provenance: "synthetic" | "file";
    file_origin_declaration: null | { source_id: string; input_sha256: string; origin: "field"; declared_by: string; evidence_ref: string };
    origin_verified: false;
    authorization_verified: false;
  };
  acquisition_state: "finalized";
  capture_extent: string;
  source_accounting: { stored_units: number; missing_units: number; dropped_units: number; gap_source_s: number };
  acquisition_completeness_verified: false;
  calibration_status: "uncalibrated";
  hardware_verified: false;
  authorization_verified: false;
  metadata_loss_in_v1: string[];
}
export interface CompanionAbsent {
  schema_version: typeof COMPANION_SCHEMA_VERSION;
  state: "absent";
  recording_id: string;
}
export interface CompanionRetained {
  schema_version: typeof COMPANION_SCHEMA_VERSION;
  state: "retained";
  recording_id: string;
  platform_session_id: string;
  capture_session_id: string;
  source_id: string;
  selected_index: number;
  source_header_sha256: string;
  source_final_sha256: string;
  wav_sha256: string;
  manifest_sha256: string;
  imported_at: string;
  actor_subject: string;
  auth_mode: CompanionAuthMode;
  job: { id: string; status: CompanionJobStatus };
  documents: CompanionDocument[];
  // Parsed from the exact reader-validated raw binding, not rebuilt by the UI.
  binding: LegacyExportBinding;
  // Reader-owned immutable JSON projection; keys are its versioned contract.
  validation: Record<string, unknown>;
}
export type AcquisitionCompanion = CompanionAbsent | CompanionRetained;
