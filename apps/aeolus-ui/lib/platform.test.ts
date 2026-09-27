import { describe, expect, test } from "bun:test";
import { canAdmin, canImport, canReview, isBootId, isIdentity, parseBoundedObject, validateObservation, type Identity, type ObservationInput } from "./platform";
import { encodeArtifact, transitionAllowed } from "./lifecycle";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const identity = (role: Identity["role"], auth_mode: Identity["auth_mode"] = "scoped_token"): Identity => ({ subject: "synthetic-test-actor", role, auth_mode, site_ids: ["synthetic-site"], device_id: role === "device" ? "synthetic-device" : null });
const observation: ObservationInput = { id: "synthetic-observation", start_s: 0, end_s: 1, label: "uncertain", notes: "Synthetic test; no biological evidence.", observer: "Synthetic declared observer", expected_revision: 0 };

describe("additive platform contracts", () => {
  test("roles disable writes without conflating local keys and scoped admins", () => {
    for (const role of ["viewer", "reviewer", "admin", "device"] as const) {
      expect(canReview(identity(role))).toBe(role === "reviewer" || role === "admin");
      expect(canAdmin(identity(role))).toBe(role === "admin");
      expect(canImport(identity(role))).toBe(false);
    }
    expect(canImport(identity("admin", "local_development_key"))).toBe(true);
    expect(canAdmin(null)).toBe(false);
  });
  test("session identity requires exact usable role and device scope", () => {
    expect(isIdentity(identity("device"))).toBe(true);
    expect(isIdentity({ ...identity("device"), device_id: null })).toBe(false);
    expect(isIdentity({ ...identity("device"), site_ids: ["a", "b"] })).toBe(false);
    expect(isIdentity({ ...identity("admin"), auth_mode: "production_verified" })).toBe(false);
    expect(isIdentity(null)).toBe(false);
  });
  test("independent observations require no detector candidate", () => {
    expect(validateObservation(observation, 1)).toBeNull();
    expect(validateObservation({ ...observation, start_s: 0.999, end_s: 1 }, 1)).toBeNull();
    for (const input of [{ ...observation, start_s: -1 }, { ...observation, start_s: 1 }, { ...observation, end_s: 2 }, { ...observation, end_s: Number.NaN }, { ...observation, start_s: Infinity }, { ...observation, observer: " " }, { ...observation, expected_revision: 1.5 }]) expect(validateObservation(input, 1)).not.toBeNull();
    expect(validateObservation({ ...observation, label: "feeding_observed", notes: "" }, 1)).not.toBeNull();
  });
  test("review context stays optional and unknown rather than automatic exposure", () => {
    expect(observation.review_context).toBeUndefined();
    expect(validateObservation({ ...observation, review_context: { protocol_id: null, evidence_refs: [], visibility: "unknown", sync_uncertainty_s: null, reviewed_coverage: false } }, 1)).toBeNull();
    expect(validateObservation({ ...observation, review_context: { protocol_id: null, evidence_refs: [], visibility: "unknown", sync_uncertainty_s: -1, reviewed_coverage: false } }, 1)).not.toBeNull();
  });
  test("uint64 boot counters never lose precision to JS Number", () => {
    expect(isBootId("18446744073709551615")).toBe(true);
    expect(isBootId("9007199254740993")).toBe(true);
    for (const bad of ["18446744073709551616", "0", "01", "1e3", "synthetic-boot", 1, 9007199254740993]) expect(isBootId(bad)).toBe(false);
  });
  test("published golden fixture uses the shared observation and uint64 contracts", () => {
    const fixtureRoot = resolve(import.meta.dir, "../../../contracts/v1/fixtures");
    const obs = JSON.parse(readFileSync(resolve(fixtureRoot, "independent-observation.valid.json"), "utf8")) as ObservationInput;
    const telemetry = JSON.parse(readFileSync(resolve(fixtureRoot, "telemetry-envelope.valid.json"), "utf8"));
    expect(validateObservation(obs, 1)).toBeNull();
    expect(isBootId(telemetry.boot_id)).toBe(true);
    expect(telemetry.provenance.source_kind).toBe("synthetic");
  });
  test("advanced JSON has bounded object-only input", () => {
    expect(parseBoundedObject('{"source_domain":"synthetic"}')).toEqual({ source_domain: "synthetic" });
    for (const bad of ["[]", "null", '"text"', "{"]) expect(() => parseBoundedObject(bad)).toThrow();
    expect(() => parseBoundedObject('{"x":"éé"}', 10)).toThrow();
  });
});

describe("local lifecycle client bounds", () => {
  test("encodes exact bytes and rejects oversized/empty artifacts", () => {
    expect(encodeArtifact(new Uint8Array([0, 255, 10, 32]))).toBe("AP8KIA==");
    expect(() => encodeArtifact(new Uint8Array())).toThrow();
    expect(() => encodeArtifact(new Uint8Array(1024 * 1024 + 1))).toThrow();
    expect(atob(encodeArtifact(new Uint8Array(1024 * 1024))).length).toBe(1024 * 1024);
  });
  test("stage, activation and declared health confirmation remain distinct", () => {
    expect(transitionAllowed("idle", "activate")).toBe(false);
    expect(transitionAllowed("staged", "activate")).toBe(true);
    expect(transitionAllowed("staged", "confirm")).toBe(false);
    expect(transitionAllowed("trial", "confirm")).toBe(true);
    expect(transitionAllowed("trial", "recover")).toBe(true);
    expect(transitionAllowed("rolled_back", "rollback")).toBe(false);
  });
});
