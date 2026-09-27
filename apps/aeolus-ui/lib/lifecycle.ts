import type { AuthMode } from "./platform";
export type TrustKey = { id: string; site_ids: string[]; public_key_hex: string; created_at: string; revoked_at: string | null };
export type LocalTarget = { id: string; device_id: string; site_id: string; target_kind: string; hardware_revision: string; simulation: true; state: "idle" | "staged" | "trial" | "healthy" | "rolled_back"; current_sha256: string; current_version: string; security_floor: number; highest_sequence: number; staged_manifest_id: string | null; trial_manifest_id: string | null; previous_sha256: string | null; revision: number; updated_at: string };
export type Transition = "activate" | "confirm" | "rollback" | "recover";
export type TargetHistory = { revision: number; action: string; actor_subject: string; auth_mode: AuthMode; created_at: string; details: Record<string, unknown> };
export const MAX_ARTIFACT_BYTES = 1024 * 1024;
export function encodeArtifact(bytes: Uint8Array): string {
  if (!bytes.length || bytes.length > MAX_ARTIFACT_BYTES) throw new Error("Choose an artifact from 1 byte to 1 MiB.");
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  return btoa(binary);
}
export function transitionAllowed(state: LocalTarget["state"], action: Transition): boolean {
  if (action === "activate") return state === "staged";
  if (action === "confirm") return state === "trial";
  return ["staged", "trial", "healthy"].includes(state);
}
