import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { Identity } from "./platform";
import { ACK_MEANINGS, canOperate, commandUnavailable, parseCommandAck, type CommandAck, type HubStateRead } from "./digital";
import { AckReceipt, DigitalCommands } from "../components/DigitalCommands";
import { DigitalHubBanner, HubAudit } from "../components/DigitalHub";
import { CalibrationEntry, DigitalCalibrations } from "../components/DigitalCalibrations";
import { AlarmList, DeviceHealthList } from "../components/DigitalHealth";
import type { CalibrationRead } from "../../../libs/proto-ts/src/calibration-v1";

const operator: Identity = { subject: "synthetic-operator", role: "operator", site_ids: ["synthetic-site"], device_id: null, auth_mode: "scoped_token" };
const hub: HubStateRead = { state: "observe", simulation: true, emission_enabled: false, binding: { device_id: "synthetic-hub", site_id: "synthetic-site", zone_id: "synthetic-zone" }, watchdogs: [{ id: "storage", healthy: true, reason: "synthetic healthy sample" }], last_transitions: [] };
const ackBase: CommandAck = { schema_version: "poseidon.command-ack.v1", command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", device_id: "synthetic-hub", received_at: "2026-09-08T00:00:00Z", outcome: "executed", reason: "Synthetic digital transition only", state_after: "inhibited", sequence_seen: "18446744073709551615" };
const calibration: CalibrationRead = { validity: "superseded", record: { schema_version: "poseidon.calibration-record.v1", record_id: "synthetic-record", supersedes_id: "synthetic-predecessor", instrument_id: "synthetic-instrument", quantity: "temperature", unit: "Cel", method: "synthetic-method", reference_id: "synthetic-reference", value: "9007199254740993.123456789", uncertainty: { value: "0.000000001", coverage_factor: "2" }, valid_from: "2026-09-08T00:00:00Z", valid_until: "2027-09-08T00:00:00Z", operator_id: "synthetic-operator-id", source_documents: ["0".repeat(64)], key_id: "synthetic-key", digital_only: true, signature: { algorithm: "Ed25519", canonicalization: "poseidon-json-v1", value: btoa("\0".repeat(64)) } } };

describe("local digital presentation gates", () => {
  test("operator is explicit and never inherited from admin", () => {
    expect(canOperate(operator)).toBe(true);
    for (const role of ["viewer", "reviewer", "admin", "device"] as const) expect(canOperate({ ...operator, role })).toBe(false);
    expect(canOperate({ ...operator, auth_mode: "local_development_key" })).toBe(false);
    expect(commandUnavailable({ ...operator, role: "admin" }, hub, "rearm")).toContain("Admin is not operator");
  });
  test("no absent, default or cross-site hub command target", () => {
    expect(commandUnavailable(operator, null, "rearm")).toContain("Refresh");
    expect(commandUnavailable(operator, { ...hub, binding: null }, "rearm")).toContain("No default target");
    expect(commandUnavailable({ ...operator, site_ids: ["synthetic-foreign-site"] }, hub, "rearm")).toContain("scope");
  });
  test("four transition controls mirror the root rulings without emit controls", () => {
    expect(commandUnavailable(operator, hub, "inhibit")).toBeNull();
    expect(commandUnavailable(operator, { ...hub, state: "armed" }, "inhibit")).toBeNull();
    expect(commandUnavailable(operator, { ...hub, state: "fault" }, "inhibit")).toContain("cannot clear");
    expect(commandUnavailable(operator, { ...hub, state: "inhibited" }, "resume")).toBeNull();
    expect(commandUnavailable(operator, { ...hub, state: "armed" }, "resume")).toContain("requires inhibited");
    expect(commandUnavailable(operator, hub, "rearm")).toBeNull();
    expect(commandUnavailable(operator, { ...hub, state: "inhibited" }, "rearm")).toContain("requires observe");
    expect(commandUnavailable(operator, { ...hub, watchdogs: [] }, "rearm")).toContain("Every watchdog");
    expect(commandUnavailable(operator, { ...hub, watchdogs: [{ id: "sensor", healthy: false, reason: "synthetic disconnect" }] }, "rearm")).toContain("Every watchdog");
    expect(commandUnavailable(operator, { ...hub, state: "fault" }, "clear-fault")).toBeNull();
    expect(commandUnavailable(operator, hub, "clear-fault")).toContain("fault");
    const html = renderToStaticMarkup(<DigitalCommands identity={operator} hub={hub} onChanged={() => {}} />);
    expect(html).toContain("non-extractable browser memory only"); expect(html).not.toContain("private_key");
    expect(html).toContain("disabled"); expect(html).not.toContain("Sign and submit emit");
  });
  test("all six ack outcomes state their actual meaning and retain uint64 text", () => {
    for (const outcome of Object.keys(ACK_MEANINGS) as CommandAck["outcome"][]) {
      const ack = parseCommandAck({ ...ackBase, outcome });
      const html = renderToStaticMarkup(<AckReceipt ack={ack} />);
      expect(html).toContain(`Actual acknowledgement: ${outcome}`);
      expect(html).toContain(ACK_MEANINGS[outcome]);
      expect(html).toContain("18446744073709551615");
      expect(html).toContain("LOCAL DIGITAL state after");
    }
  });
  test("hub banner and audit state boundaries rather than hardware readiness", () => {
    const html = renderToStaticMarkup(<DigitalHubBanner hub={hub} error={null} loading={false} onRefresh={() => {}} />);
    expect(html).toContain("LOCAL DIGITAL state"); expect(html).toContain("Emit entry is always refused");
    expect(html).toContain("synthetic-hub"); expect(html).toContain("Not hardware connectivity");
    expect(renderToStaticMarkup(<HubAudit hub={hub} />)).toContain("No recorded transitions");
    expect(renderToStaticMarkup(<DigitalHubBanner hub={null} error="Unavailable" loading={false} onRefresh={() => {}} />)).toContain("No current hub-state response");
  });
  test("calibration view keeps exact decimals, validity and predecessor without physical claims", () => {
    const html = renderToStaticMarkup(<CalibrationEntry item={calibration} />);
    for (const value of ["DIGITAL_ONLY=true", "Not physical calibration", "superseded", "synthetic-predecessor", "9007199254740993.123456789", "0.000000001", "synthetic-key"]) expect(html).toContain(value);
    const malformed = { ...calibration, record: { ...calibration.record, digital_only: false } } as unknown as CalibrationRead;
    expect(renderToStaticMarkup(<CalibrationEntry item={malformed} />)).toContain("failed the shared digital-only contract");
  });
  test("health, alarms and calibration initial states contain no invented records", () => {
    expect(renderToStaticMarkup(<DeviceHealthList version={0} />)).toContain("Refreshing receipt health");
    expect(renderToStaticMarkup(<AlarmList identity={operator} version={0} onChanged={() => {}} />)).toContain("Refreshing digital alarms");
    expect(renderToStaticMarkup(<DigitalCalibrations version={0} />)).toContain("Refreshing digital calibration records");
  });
});
