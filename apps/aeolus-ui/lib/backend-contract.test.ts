import { describe, expect, test } from "bun:test";
import { matchBackendRequest } from "./backend-contract";

function match(method: string, path: string, query = "") {
  return matchBackendRequest(method, path.split("/").filter(Boolean), new URLSearchParams(query));
}

describe("backend proxy contract", () => {
  test("allows frozen routes and methods", () => {
    expect(match("GET", "/api/v1/status")).not.toBeNull();
    expect(match("POST", "/api/v1/recordings")).not.toBeNull();
    expect(match("GET", "/api/v1/jobs/job_1")).not.toBeNull();
    expect(match("PUT", "/api/v1/events/evt_1/review")).not.toBeNull();
    expect(match("GET", "/api/v1/recordings/rec_1/waveform", "points=512")).not.toBeNull();
    expect(match("POST", "/api/v1/recordings/rec_1/video")).not.toBeNull();
  });

  test("allows only exact additive platform routes with bounded bodies", () => {
    for (const path of ["identity", "devices", "principals", "audit", "telemetry", "acquisition-sessions", "recordings/rec_1/observations", "recordings/rec_1/observations/obs_1/history", "recordings/rec_1/acquisition-session", "devices/dev_1/aquilon-mapping", "lifecycle/keys", "lifecycle/targets/target_1/history"]) expect(match("GET", `/api/v1/${path}`)).not.toBeNull();
    expect(match("POST", "/api/v1/telemetry")?.bodyLimit).toBe(16 * 1024);
    expect(match("POST", "/api/v1/devices")?.bodyLimit).toBe(64 * 1024);
    expect(match("PUT", "/api/v1/recordings/rec_1/observations/obs_1")?.bodyLimit).toBe(64 * 1024);
    expect(match("PUT", "/api/v1/devices/dev_1/aquilon-mapping")?.bodyLimit).toBe(64 * 1024);
    expect(match("POST", "/api/v1/lifecycle/targets/target_1/stage")?.bodyLimit).toBe(1536 * 1024);
    for (const action of ["activate", "confirm", "rollback", "recover"]) expect(match("POST", `/api/v1/lifecycle/targets/target_1/${action}`)?.bodyLimit).toBe(0);
    expect(match("POST", "/api/v1/principals/p_1/rotate")).not.toBeNull();
    expect(match("POST", "/api/v1/lifecycle/keys/key_1/revoke")).not.toBeNull();
  });

  test("rejects platform path traversal, unknown endpoints, query duplicates and unauthorized proxy verbs", () => {
    for (const path of ["devices/../revoke", "devices/d_1/flash", "lifecycle/sign", "lifecycle/targets/t_1/install", "lifecycle/targets/t_1/shell", "recordings/r_1/observations/o_1/delete"]) expect(match("POST", `/api/v1/${path}`)).toBeNull();
    expect(match("DELETE", "/api/v1/recordings/r_1/observations/o_1")).toBeNull();
    expect(match("GET", "/api/v1/lifecycle/keys", "limit=10")).toBeNull();
    expect(match("GET", "/api/v1/telemetry", "site_id=x&site_id=y")).toBeNull();
    expect(match("GET", "/api/v1/telemetry", "device_id=..")).toBeNull();
    expect(match("GET", "/api/v1/telemetry", "device_id=dev_1&site_id=site_1&limit=25&offset=0")).not.toBeNull();
    expect(match("GET", "/api/v1/audit", "site_id=site_1")).toBeNull();
    expect(match("POST", "/api/v1/lifecycle/targets/t_1/stage", "url=https://example.com")).toBeNull();
  });

  test("bounds tranche 3 routes and never admits direct state/output setters", () => {
    for (const path of ["device-health", "alarms", "commands", "hub-state", "command-keys", "command-sequence/hub_1", "commands/command_1", "devices/d_1/health-profile"]) expect(match("GET", `/api/v1/${path}`)).not.toBeNull();
    for (const path of ["commands", "command-keys"]) expect(match("POST", `/api/v1/${path}`)?.bodyLimit).toBe(16 * 1024);
    expect(match("POST", "/api/v1/alarms/a_1/acknowledge")?.bodyLimit).toBe(0);
    expect(match("POST", "/api/v1/command-keys/k_1/revoke")?.bodyLimit).toBe(0);
    expect(match("PUT", "/api/v1/devices/d_1/health-profile")?.bodyLimit).toBe(16 * 1024);
    for (const path of ["hub-state", "hub-state/emit", "hub-state/inject", "commands/c_1/execute", "devices/d_1/output", "command-keys/k_1/private"]) expect(match("POST", `/api/v1/${path}`)).toBeNull();
    expect(match("GET", "/api/v1/device-health", "limit=2&limit=3")).toBeNull();
    expect(match("GET", "/api/v1/hub-state", "site_id=guessed")).toBeNull();
    expect(match("PUT", "/api/v1/devices/../health-profile")).toBeNull();
  });

  test("rejects open-proxy paths and wrong methods", () => {
    expect(match("GET", "/https://example.com")).toBeNull();
    expect(match("DELETE", "/api/v1/events/evt_1")).toBeNull();
    expect(match("POST", "/api/v1/status")).toBeNull();
    expect(match("GET", "/api/v1/recordings/../../healthz")).toBeNull();
  });

  test("validates bounded pagination and filter enums", () => {
    expect(match("GET", "/api/v1/events", "limit=200&offset=0&review=unreviewed")).not.toBeNull();
    expect(match("GET", "/api/v1/events", "limit=201")).toBeNull();
    expect(match("GET", "/api/v1/events", "review=detected")).toBeNull();
    expect(match("GET", "/api/v1/events", "limit=20&limit=30")).toBeNull();
    expect(match("GET", "/api/v1/jobs", "target=https://example.com")).toBeNull();
  });
});
