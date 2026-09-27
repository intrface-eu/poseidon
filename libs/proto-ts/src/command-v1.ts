// Digital-only commands. No transport or private-key persistence.
export const COMMAND_KINDS = ["inhibit", "resume", "rearm", "clear-fault", "wiper-run", "health-request", "config-apply"] as const;
export type CommandKind = typeof COMMAND_KINDS[number];
export type HubState = "observe" | "armed" | "inhibited" | "fault" | "emit";
export type Signature = { algorithm: "Ed25519"; canonicalization: "poseidon-json-v1"; value: string };
export type Command = { schema_version: "poseidon.command.v1"; command_id: string; site_id: string; zone_id: string; device_id: string; principal_id: string; key_id: string; sequence: string; issued_at: string; expires_at: string; kind: CommandKind; params: Record<string, unknown>; signature: Signature };
export type CommandAck = { schema_version: "poseidon.command-ack.v1"; command_id: string; device_id: string; received_at: string; outcome: "accepted" | "rejected" | "expired" | "duplicate" | "executed" | "failed"; reason: string; state_after: HubState; sequence_seen: string };
export type CommandKey = { key_id: string; principal_id: string; public_key_hex: string; site_ids: string[]; created_at: string; revoked_at: string | null };
export type CommandContext = { principal_id: string; device_id: string; allowed_kinds: CommandKind[]; sequence_seen: string; keys: CommandKey[] };
export type HealthProfile = { schema_version: "poseidon.device-health-profile.v1"; zone_id: string; stale_after_s: number; offline_after_s: number };
export type DeviceHealth = { device_id: string; site_id: string; zone_id: string | null; health: "online" | "stale" | "offline" | "revoked" | "unprofiled"; last_telemetry_at: string | null; age_s: number | null; profile: HealthProfile | null };
export type HubBinding = { device_id: string; site_id: string; zone_id: string };
export type Transition = { id: number; from_state: HubState; to_state: HubState; cause_id: string; command_id: string | null; reason: string; created_at: string };
export type HubStateRead = { state: HubState; simulation: true; emission_enabled: false; binding: HubBinding | null; watchdogs: { id: string; healthy: boolean; reason: string }[]; last_transitions: Transition[] };
export type Alarm = { id: string; source: "device" | "hub"; site_id: string; device_id: string; severity: "warning" | "critical"; reason: string; opened_at: string; cleared_at: string | null; acknowledged_by: string | null; acknowledged_at: string | null };
export type DigitalConfig = { schema_version: "poseidon.digital-config.v2"; simulation: true; health_interval_s: number };

const encoder = new TextEncoder();
export function fail(message = "invalid digital contract"): never { throw new Error(message); }
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  return value as Record<string, unknown>;
}
export function exact(value: unknown, keys: string[]): Record<string, unknown> {
  const row = object(value);
  if (Object.keys(row).sort().join("\0") !== [...keys].sort().join("\0")) fail("missing or unknown fields");
  return row;
}
export function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(value) || /[\r\n]/.test(value)) fail();
  return value;
}
export function uint64(value: unknown): string {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,19})$/.test(value) || /[\r\n]/.test(value) || BigInt(value) > 18446744073709551615n) fail("invalid uint64 decimal text");
  return value;
}
export function utc(value: unknown): number {
  if (typeof value !== "string" || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?Z$/.test(value) || /[\r\n]/.test(value)) fail("invalid UTC timestamp");
  const ms = Date.parse(value);
  if (!Number.isFinite(ms) || new Date(ms).toISOString().slice(0, 19) !== value.slice(0, 19) || value.startsWith("0000")) fail("invalid calendar date");
  return ms;
}
function unicode(value: string): void {
  for (let i = 0; i < value.length; i++) {
    const c = value.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      const n = value.charCodeAt(++i);
      if (!(n >= 0xdc00 && n <= 0xdfff)) fail("invalid Unicode");
    } else if (c >= 0xdc00 && c <= 0xdfff) fail("invalid Unicode");
  }
}
function quote(value: string): string {
  unicode(value);
  return JSON.stringify(value).replace(/[-￿]/g, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
function compareCodepoints(a: string, b: string): number {
  const x = Array.from(a, c => c.codePointAt(0)!); const y = Array.from(b, c => c.codePointAt(0)!);
  for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] - y[i];
  return x.length - y.length;
}
/** Same frozen Python poseidon-json-v1 domain, restricted to safe integer numbers. */
export function canonicalJson(value: unknown, depth = 0): string {
  if (depth > 16) fail("JSON nesting exceeds 16");
  if (value === null) return "null";
  if (typeof value === "string") return quote(value);
  if (typeof value === "boolean") return String(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value) || Object.is(value, -0)) fail("use integer numbers or decimal text");
    return String(value);
  }
  if (Array.isArray(value)) return `[${value.map(v => canonicalJson(v, depth + 1)).join(",")}]`;
  const row = object(value);
  return `{${Object.keys(row).sort(compareCodepoints).map(k => `${quote(k)}:${canonicalJson(row[k], depth + 1)}`).join(",")}}`;
}
/** The existing shared signed-manifest domain, not a new signing protocol. */
export function signingBytes(payload: Record<string, unknown>, keyId: string): Uint8Array {
  identifier(keyId);
  return encoder.encode(`poseidon.signed-manifest.v1\0${keyId}\0${canonicalJson(payload)}`);
}
export function payloadBytes(document: { key_id: string; signature: Signature }): Uint8Array {
  const { signature: _signature, ...payload } = document;
  return signingBytes(payload, document.key_id);
}
export function signature(value: unknown): void {
  const row = exact(value, ["algorithm", "canonicalization", "value"]);
  if (row.algorithm !== "Ed25519" || row.canonicalization !== "poseidon-json-v1" || typeof row.value !== "string" || !/^[A-Za-z0-9+/]{86}==$/.test(row.value)) fail("invalid signature metadata");
  let raw: string;
  try { raw = atob(row.value); } catch { fail("invalid base64"); }
  if (raw.length !== 64 || btoa(raw) !== row.value) fail("noncanonical signature base64");
}
/** JSON parser that rejects duplicate keys and noninteger numeric lexemes. */
export function decodeWire(text: string, maximum = 16384): Record<string, unknown> {
  if (encoder.encode(text).length > maximum) fail("wire byte limit");
  let pos = 0;
  const ws = () => { while (/\s/.test(text[pos] ?? "") && pos < text.length) { if (!/[ \t\r\n]/.test(text[pos])) fail(); pos++; } };
  const str = (): string => {
    const start = pos++;
    while (pos < text.length) {
      const c = text[pos++];
      if (c === "\\") { pos++; continue; }
      if (c === '"') { const v: string = JSON.parse(text.slice(start, pos)); unicode(v); return v; }
    }
    return fail("unterminated JSON string");
  };
  const parse = (depth: number): unknown => {
    if (depth > 16) fail("JSON nesting exceeds 16"); ws();
    if (text[pos] === '"') return str();
    if (text[pos] === "{") {
      pos++; ws(); const row: Record<string, unknown> = Object.create(null);
      if (text[pos] === "}") { pos++; return row; }
      while (true) {
        ws(); if (text[pos] !== '"') fail(); const key = str(); ws(); if (text[pos++] !== ":" || Object.hasOwn(row, key)) fail("duplicate key or missing colon");
        row[key] = parse(depth + 1); ws(); const c = text[pos++]; if (c === "}") return row; if (c !== ",") fail();
      }
    }
    if (text[pos] === "[") {
      pos++; ws(); const values: unknown[] = []; if (text[pos] === "]") { pos++; return values; }
      while (true) { values.push(parse(depth + 1)); ws(); const c = text[pos++]; if (c === "]") return values; if (c !== ",") fail(); }
    }
    for (const [literal, value] of [["true", true], ["false", false], ["null", null]] as const) if (text.startsWith(literal, pos)) { pos += literal.length; return value; }
    const match = /^-?(?:0|[1-9][0-9]*)/.exec(text.slice(pos)); if (!match) fail("invalid JSON token"); pos += match[0].length;
    const n = Number(match[0]); if (!Number.isSafeInteger(n) || Object.is(n, -0)) fail(); return n;
  };
  const value = parse(0); ws(); if (pos !== text.length) fail("trailing JSON data"); return object(value);
}
export function migrateConfig(value: unknown): DigitalConfig {
  const row = object(value); const v = row.schema_version;
  if (v !== "poseidon.digital-config.v1" && v !== "poseidon.digital-config.v2") fail("unknown config version");
  exact(row, v === "poseidon.digital-config.v1" ? ["schema_version", "health_interval_s"] : ["schema_version", "health_interval_s", "simulation"]);
  if (!Number.isInteger(row.health_interval_s) || Number(row.health_interval_s) < 1 || Number(row.health_interval_s) > 3600 || (v === "poseidon.digital-config.v2" && row.simulation !== true)) fail();
  return { schema_version: "poseidon.digital-config.v2", simulation: true, health_interval_s: Number(row.health_interval_s) };
}
function uuid(value: unknown): void { if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value) || value.length !== 36) fail("invalid UUID4"); }
export function parseCommand(value: unknown): Command {
  const row = exact(typeof value === "string" ? decodeWire(value) : value, ["schema_version", "command_id", "site_id", "zone_id", "device_id", "principal_id", "key_id", "sequence", "issued_at", "expires_at", "kind", "params", "signature"]);
  if (row.schema_version !== "poseidon.command.v1" || !COMMAND_KINDS.includes(row.kind as CommandKind)) fail();
  uuid(row.command_id); for (const name of ["site_id", "zone_id", "device_id", "principal_id", "key_id"]) identifier(row[name]); uint64(row.sequence); signature(row.signature);
  const duration = utc(row.expires_at) - utc(row.issued_at); if (!(duration > 0 && duration <= 600000)) fail("command lifetime");
  const params = object(row.params); if (encoder.encode(canonicalJson(params)).length > 4096) fail("params byte limit");
  if (row.kind === "config-apply") { exact(params, ["config"]); migrateConfig(params.config); } else exact(params, []);
  return JSON.parse(canonicalJson(row)) as Command;
}
export function parseCommandAck(value: unknown, retained = false): CommandAck {
  if (typeof retained !== "boolean" || retained) fail("retained acknowledgement rejected");
  const row = exact(typeof value === "string" ? decodeWire(value) : value, ["schema_version", "command_id", "device_id", "received_at", "outcome", "reason", "state_after", "sequence_seen"]);
  if (row.schema_version !== "poseidon.command-ack.v1" || !["accepted", "rejected", "expired", "duplicate", "executed", "failed"].includes(String(row.outcome)) || !["observe", "armed", "inhibited", "fault"].includes(String(row.state_after)) || typeof row.reason !== "string" || Array.from(row.reason).length < 1 || Array.from(row.reason).length > 256) fail();
  uuid(row.command_id); identifier(row.device_id); utc(row.received_at); uint64(row.sequence_seen);
  return JSON.parse(canonicalJson(row)) as CommandAck;
}

function guard(check: () => void): boolean { try { check(); return true; } catch { return false; } }
export function isCommandKey(value: unknown): value is CommandKey { return guard(() => {
  const r = exact(value, ["key_id", "principal_id", "public_key_hex", "site_ids", "created_at", "revoked_at"]);
  identifier(r.key_id); identifier(r.principal_id); utc(r.created_at); if (r.revoked_at !== null) utc(r.revoked_at);
  if (typeof r.public_key_hex !== "string" || !/^[a-f0-9]{64}$/.test(r.public_key_hex) || r.public_key_hex.length !== 64 || !Array.isArray(r.site_ids) || !r.site_ids.length) fail();
  r.site_ids.forEach(identifier);
}); }
export function isCommandContext(value: unknown): value is CommandContext { return guard(() => {
  const r = exact(value, ["principal_id", "device_id", "allowed_kinds", "sequence_seen", "keys"]);
  identifier(r.principal_id); identifier(r.device_id); uint64(r.sequence_seen);
  if (!Array.isArray(r.allowed_kinds) || r.allowed_kinds.some(k => !COMMAND_KINDS.includes(k)) || !Array.isArray(r.keys) || r.keys.some(k => !isCommandKey(k) || k.principal_id !== r.principal_id || k.revoked_at !== null)) fail();
}); }
export function isHubBinding(value: unknown): value is HubBinding { return guard(() => {
  const r = exact(value, ["device_id", "site_id", "zone_id"]); Object.values(r).forEach(identifier);
}); }
export function isHealthProfile(value: unknown): value is HealthProfile { return guard(() => {
  const r = exact(value, ["schema_version", "zone_id", "stale_after_s", "offline_after_s"]); identifier(r.zone_id);
  if (r.schema_version !== "poseidon.device-health-profile.v1" || !Number.isInteger(r.stale_after_s) || !Number.isInteger(r.offline_after_s) || Number(r.stale_after_s) <= 0 || Number(r.offline_after_s) <= Number(r.stale_after_s) || Number(r.offline_after_s) > 86400) fail();
}); }
export function isDeviceHealth(value: unknown): value is DeviceHealth { return guard(() => {
  const r = exact(value, ["device_id", "site_id", "zone_id", "health", "last_telemetry_at", "age_s", "profile"]); identifier(r.device_id); identifier(r.site_id);
  if (r.zone_id !== null) identifier(r.zone_id); if (r.last_telemetry_at !== null) utc(r.last_telemetry_at);
  if (r.age_s !== null && (typeof r.age_s !== "number" || !Number.isFinite(r.age_s) || r.age_s < 0)) fail();
  if (!["online", "stale", "offline", "revoked", "unprofiled"].includes(String(r.health)) || (r.profile !== null && !isHealthProfile(r.profile)) || (r.profile === null && r.zone_id !== null)) fail();
}); }
export function isHubStateRead(value: unknown): value is HubStateRead { return guard(() => {
  const r = exact(value, ["state", "simulation", "emission_enabled", "binding", "watchdogs", "last_transitions"]);
  const states = ["observe", "armed", "inhibited", "fault"];
  if (!states.includes(String(r.state)) || r.simulation !== true || r.emission_enabled !== false || (r.binding !== null && !isHubBinding(r.binding)) || !Array.isArray(r.watchdogs) || !Array.isArray(r.last_transitions) || r.last_transitions.length > 10) fail();
  for (const w of r.watchdogs) { const d = exact(w, ["id", "healthy", "reason"]); identifier(d.id); if (typeof d.healthy !== "boolean" || typeof d.reason !== "string") fail(); }
  for (const t of r.last_transitions) { const d = exact(t, ["id", "from_state", "to_state", "cause_id", "command_id", "reason", "created_at"]); if (!Number.isSafeInteger(d.id) || !states.includes(String(d.from_state)) || !states.includes(String(d.to_state)) || typeof d.reason !== "string") fail(); identifier(d.cause_id); if (d.command_id !== null) uuid(d.command_id); utc(d.created_at); }
}); }
export function isAlarm(value: unknown): value is Alarm { return guard(() => {
  const r = exact(value, ["id", "source", "site_id", "device_id", "severity", "reason", "opened_at", "cleared_at", "acknowledged_by", "acknowledged_at"]);
  for (const k of ["id", "site_id", "device_id"]) identifier(r[k]); utc(r.opened_at); if (r.cleared_at !== null) utc(r.cleared_at); if (r.acknowledged_at !== null) utc(r.acknowledged_at); if (r.acknowledged_by !== null) identifier(r.acknowledged_by);
  if (!["device", "hub"].includes(String(r.source)) || !["warning", "critical"].includes(String(r.severity)) || typeof r.reason !== "string") fail();
}); }

