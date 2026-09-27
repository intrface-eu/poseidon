import { COMPANION_DOCUMENT_ROLES, COMPANION_MAX_REQUEST_BYTES } from "../../../libs/proto-ts/src/companion-v1";

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const REVIEW_FILTERS = new Set(["unreviewed", "confirmed_feeding", "non_feeding", "uncertain"]);

export const MAX_MULTIPART_BYTES = 65 * 1024 * 1024;
export const MAX_JSON_BYTES = 16 * 1024;

export type ProxyMatch = {
  bodyLimit: number;
  path: string;
  timeoutMs: number;
};

function oneValue(params: URLSearchParams, name: string): string | null {
  const values = params.getAll(name);
  return values.length <= 1 ? values[0] ?? null : "__duplicate__";
}

function integerParam(
  params: URLSearchParams,
  name: string,
  minimum: number,
  maximum?: number,
): boolean {
  const value = oneValue(params, name);
  if (value === null) return true;
  if (!/^(0|[1-9]\d*)$/.test(value)) return false;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum && (maximum === undefined || parsed <= maximum);
}

function onlyQuery(params: URLSearchParams, names: readonly string[]): boolean {
  const allowed = new Set(names);
  return Array.from(params.keys()).every((key) => allowed.has(key));
}

function pagination(params: URLSearchParams): boolean {
  return integerParam(params, "limit", 1, 200) && integerParam(params, "offset", 0);
}

function exactPath(parts: readonly string[], expected: readonly string[]): boolean {
  return parts.length === expected.length && parts.every((part, index) => part === expected[index]);
}

function safeId(value: string | undefined): value is string {
  return typeof value === "string" && SAFE_ID.test(value);
}

export function matchBackendRequest(
  method: string,
  parts: readonly string[],
  params: URLSearchParams,
): ProxyMatch | null {
  const upper = method.toUpperCase();
  const path = `/${parts.map(encodeURIComponent).join("/")}`;

  if (upper === "GET" && exactPath(parts, ["healthz"]) && onlyQuery(params, [])) {
    return { bodyLimit: 0, path, timeoutMs: 10_000 };
  }
  if (upper === "GET" && exactPath(parts, ["api", "v1", "status"]) && onlyQuery(params, [])) {
    return { bodyLimit: 0, path, timeoutMs: 15_000 };
  }
  if (upper === "POST" && exactPath(parts, ["api", "v1", "demo"]) && onlyQuery(params, [])) {
    return { bodyLimit: 0, path, timeoutMs: 30_000 };
  }
  if (upper === "POST" && exactPath(parts, ["api", "v1", "recordings"]) && onlyQuery(params, [])) {
    return { bodyLimit: MAX_MULTIPART_BYTES, path, timeoutMs: 120_000 };
  }
  if (upper === "GET" && exactPath(parts, ["api", "v1", "jobs"]) && onlyQuery(params, ["limit", "offset"]) && pagination(params)) {
    return { bodyLimit: 0, path, timeoutMs: 15_000 };
  }
  if (upper === "GET" && parts.length === 4 && exactPath(parts.slice(0, 3), ["api", "v1", "jobs"]) && safeId(parts[3]) && onlyQuery(params, [])) {
    return { bodyLimit: 0, path, timeoutMs: 15_000 };
  }
  if (upper === "GET" && exactPath(parts, ["api", "v1", "recordings"]) && onlyQuery(params, ["limit", "offset"]) && pagination(params)) {
    return { bodyLimit: 0, path, timeoutMs: 15_000 };
  }
  if (upper === "GET" && parts.length === 4 && exactPath(parts.slice(0, 3), ["api", "v1", "recordings"]) && safeId(parts[3]) && onlyQuery(params, [])) {
    return { bodyLimit: 0, path, timeoutMs: 15_000 };
  }
  if (upper === "GET" && exactPath(parts, ["api", "v1", "events"]) && onlyQuery(params, ["recording_id", "review", "limit", "offset"]) && pagination(params)) {
    const recordingId = oneValue(params, "recording_id");
    const review = oneValue(params, "review");
    if (recordingId !== null && !safeId(recordingId)) return null;
    if (review !== null && !REVIEW_FILTERS.has(review)) return null;
    return { bodyLimit: 0, path, timeoutMs: 15_000 };
  }
  if (upper === "GET" && parts.length === 4 && exactPath(parts.slice(0, 3), ["api", "v1", "events"]) && safeId(parts[3]) && onlyQuery(params, [])) {
    return { bodyLimit: 0, path, timeoutMs: 15_000 };
  }
  if (upper === "PUT" && parts.length === 5 && exactPath(parts.slice(0, 3), ["api", "v1", "events"]) && safeId(parts[3]) && parts[4] === "review" && onlyQuery(params, [])) {
    return { bodyLimit: MAX_JSON_BYTES, path, timeoutMs: 20_000 };
  }
  if (parts.length === 5 && exactPath(parts.slice(0, 3), ["api", "v1", "recordings"]) && safeId(parts[3]) && parts[4] === "waveform" && upper === "GET" && onlyQuery(params, ["points"]) && integerParam(params, "points", 16, 2048)) {
    return { bodyLimit: 0, path, timeoutMs: 20_000 };
  }
  if (parts.length === 5 && exactPath(parts.slice(0, 3), ["api", "v1", "recordings"]) && safeId(parts[3]) && parts[4] === "video" && onlyQuery(params, [])) {
    if (upper === "GET") return { bodyLimit: 0, path, timeoutMs: 120_000 };
    if (upper === "POST") return { bodyLimit: MAX_MULTIPART_BYTES, path, timeoutMs: 120_000 };
  }
  // Platform additions remain an explicit allowlist, never a generic JSON proxy.
  if (exactPath(parts.slice(0, 2), ["api", "v1"])) {
    const resource = parts[2];
    // Tranche 3 is local digital state, not a device/output passthrough.
    if (parts.length === 3 && upper === "PUT" && resource === "hub-binding" && onlyQuery(params, [])) return { bodyLimit: MAX_JSON_BYTES, path, timeoutMs: 20_000 };
    if (parts.length === 3 && upper === "GET" && ["device-health", "alarms", "commands", "calibrations"].includes(resource) && onlyQuery(params, ["limit", "offset"]) && pagination(params)) return { bodyLimit: 0, path, timeoutMs: 15_000 };
    if (parts.length === 3 && upper === "GET" && ["hub-state", "hub-binding", "command-keys"].includes(resource) && onlyQuery(params, [])) return { bodyLimit: 0, path, timeoutMs: 15_000 };
    if (parts.length === 3 && upper === "POST" && ["commands", "command-keys", "calibrations"].includes(resource) && onlyQuery(params, [])) return { bodyLimit: MAX_JSON_BYTES, path, timeoutMs: 20_000 };
    if (parts.length === 4 && upper === "GET" && ["commands", "command-sequence", "command-context", "calibrations"].includes(resource) && safeId(parts[3]) && onlyQuery(params, [])) return { bodyLimit: 0, path, timeoutMs: 15_000 };
    if (parts.length === 5 && upper === "POST" && safeId(parts[3]) && onlyQuery(params, []) && ((resource === "alarms" && parts[4] === "acknowledge") || (resource === "command-keys" && parts[4] === "revoke"))) return { bodyLimit: 0, path, timeoutMs: 20_000 };
    if (resource === "devices" && parts.length === 5 && safeId(parts[3]) && parts[4] === "health-profile" && ["GET", "PUT"].includes(upper) && onlyQuery(params, [])) return { bodyLimit: upper === "GET" ? 0 : MAX_JSON_BYTES, path, timeoutMs: 20_000 };
    if (resource === "acquisition-sessions" && upper === "POST" && parts.length === 5 && safeId(parts[3]) && parts[4] === "recordings" && onlyQuery(params, [])) return { bodyLimit: COMPANION_MAX_REQUEST_BYTES, path, timeoutMs: 120_000 };
    if (resource === "recordings" && upper === "GET" && safeId(parts[3]) && parts[4] === "acquisition-companion" && onlyQuery(params, [])) {
      if (parts.length === 5) return { bodyLimit: 0, path, timeoutMs: 30_000 };
      if (parts.length === 7 && parts[5] === "documents" && COMPANION_DOCUMENT_ROLES.includes(parts[6] as (typeof COMPANION_DOCUMENT_ROLES)[number])) return { bodyLimit: 0, path, timeoutMs: 30_000 };
    }
    if (resource === "lifecycle" && onlyQuery(params, [])) {
      if (parts.length === 4 && ["keys", "targets"].includes(parts[3]) && ["GET", "POST"].includes(upper)) return { bodyLimit: upper === "GET" ? 0 : 64 * 1024, path, timeoutMs: 20_000 };
      if (parts[3] === "keys" && parts.length === 6 && safeId(parts[4]) && parts[5] === "revoke" && upper === "POST") return { bodyLimit: 0, path, timeoutMs: 20_000 };
      if (parts[3] === "targets" && safeId(parts[4])) {
        if (upper === "GET" && (parts.length === 5 || (parts.length === 6 && parts[5] === "history"))) return { bodyLimit: 0, path, timeoutMs: 20_000 };
        if (upper === "POST" && parts.length === 6 && ["stage", "activate", "confirm", "rollback", "recover"].includes(parts[5])) return { bodyLimit: parts[5] === "stage" ? 1536 * 1024 : 0, path, timeoutMs: 30_000 };
      }
    }
    if (resource === "devices" && parts.length === 5 && safeId(parts[3]) && parts[4] === "aquilon-mapping" && ["GET", "PUT"].includes(upper) && onlyQuery(params, [])) return { bodyLimit: upper === "GET" ? 0 : 64 * 1024, path, timeoutMs: 20_000 };
    const listResources = ["devices", "principals", "acquisition-sessions", "audit", "telemetry"];
    if (upper === "GET" && parts.length === 3 && resource === "identity" && onlyQuery(params, [])) {
      return { bodyLimit: 0, path, timeoutMs: 15_000 };
    }
    if (upper === "GET" && parts.length === 3 && listResources.includes(resource)) {
      const filters = resource === "telemetry" ? ["device_id", "site_id"] : [];
      if (!onlyQuery(params, ["limit", "offset", ...filters]) || !pagination(params)) return null;
      if (filters.some((key) => oneValue(params, key) !== null && !safeId(oneValue(params, key) ?? undefined))) return null;
      return { bodyLimit: 0, path, timeoutMs: 15_000 };
    }
    if (upper === "POST" && parts.length === 3 && ["devices", "principals", "acquisition-sessions", "telemetry"].includes(resource) && onlyQuery(params, [])) {
      return { bodyLimit: resource === "telemetry" ? MAX_JSON_BYTES : 64 * 1024, path, timeoutMs: 20_000 };
    }
    if (upper === "GET" && parts.length === 4 && ["devices", "acquisition-sessions"].includes(resource) && safeId(parts[3]) && onlyQuery(params, [])) {
      return { bodyLimit: 0, path, timeoutMs: 15_000 };
    }
    if (upper === "POST" && parts.length === 5 && safeId(parts[3]) && onlyQuery(params, []) && ((resource === "devices" && parts[4] === "revoke") || (resource === "principals" && ["rotate", "revoke"].includes(parts[4])))) {
      return { bodyLimit: MAX_JSON_BYTES, path, timeoutMs: 20_000 };
    }
    if (resource === "recordings" && safeId(parts[3])) {
      if (parts.length === 5 && parts[4] === "acquisition-session" && onlyQuery(params, []) && ["GET", "PUT"].includes(upper)) {
        return { bodyLimit: upper === "GET" ? 0 : MAX_JSON_BYTES, path, timeoutMs: 20_000 };
      }
      if (parts[4] === "observations") {
        if (upper === "GET" && (parts.length === 5 || (parts.length === 7 && safeId(parts[5]) && parts[6] === "history")) && onlyQuery(params, ["limit", "offset"]) && pagination(params)) {
          return { bodyLimit: 0, path, timeoutMs: 15_000 };
        }
        if (((upper === "POST" && parts.length === 5) || (upper === "PUT" && parts.length === 6 && safeId(parts[5]))) && onlyQuery(params, [])) {
          return { bodyLimit: 64 * 1024, path, timeoutMs: 20_000 };
        }
      }
    }
  }
  return null;
}
