import { canonicalJson, decodeWire, exact, fail, identifier, object, signature, utc, type Signature } from "./command-v1";
export const SUPPORTED_UCUM = ["1", "%", "Cel", "K", "Pa", "kPa", "m", "s", "Hz", "V", "mV", "A", "W", "mg/L", "g/L", "m/s", "dB", "[pH]"] as const;
export type CalibrationRecord = { schema_version: "poseidon.calibration-record.v1"; record_id: string; supersedes_id: string | null; instrument_id: string; quantity: string; unit: string; method: string; reference_id: string; value: string; uncertainty: { value: string; coverage_factor: string }; valid_from: string; valid_until: string; operator_id: string; source_documents: string[]; key_id: string; digital_only: true; signature: Signature };
export type CalibrationRead = { record: CalibrationRecord; validity: "current" | "expired" | "not_yet_valid" | "superseded" };
export function decimal(value: unknown): string {
  if (typeof value !== "string" || value.length > 80 || !/^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$/.test(value) || /[\r\n]/.test(value) || value === "-0") fail("invalid canonical decimal text");
  return value;
}
export function parseCalibration(value: unknown): CalibrationRecord {
  const row = exact(typeof value === "string" ? decodeWire(value) : value, ["schema_version", "record_id", "supersedes_id", "instrument_id", "quantity", "unit", "method", "reference_id", "value", "uncertainty", "valid_from", "valid_until", "operator_id", "source_documents", "key_id", "digital_only", "signature"]);
  if (row.schema_version !== "poseidon.calibration-record.v1" || row.digital_only !== true) fail();
  for (const key of ["record_id", "instrument_id", "quantity", "method", "reference_id", "operator_id", "key_id"]) identifier(row[key]);
  if (row.supersedes_id !== null) identifier(row.supersedes_id);
  if (row.record_id === row.supersedes_id) fail("self-supersession");
  if (typeof row.unit !== "string" || !(SUPPORTED_UCUM as readonly string[]).includes(row.unit)) fail("unsupported UCUM unit");
  decimal(row.value); const u = exact(object(row.uncertainty), ["value", "coverage_factor"]);
  if (decimal(u.value).startsWith("-") || decimal(u.coverage_factor).startsWith("-") || u.coverage_factor === "0") fail();
  if (utc(row.valid_until) <= utc(row.valid_from)) fail();
  if (!Array.isArray(row.source_documents) || row.source_documents.length < 1 || row.source_documents.length > 32 || row.source_documents.some(v => typeof v !== "string" || !/^[a-f0-9]{64}$/.test(v) || v.length !== 64) || new Set(row.source_documents).size !== row.source_documents.length) fail();
  signature(row.signature); return JSON.parse(canonicalJson(row)) as CalibrationRecord;
}
export function isCalibrationRead(value: unknown): value is CalibrationRead {
  try { const r = exact(value, ["record", "validity"]); parseCalibration(r.record); return ["current", "expired", "not_yet_valid", "superseded"].includes(String(r.validity)); } catch { return false; }
}

