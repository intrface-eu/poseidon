import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { verify, createPublicKey } from "node:crypto";
import { parseCommand, parseCommandAck, decodeWire, canonicalJson, payloadBytes, migrateConfig } from "../../libs/proto-ts/src/command-v1";
import { parseCalibration } from "../../libs/proto-ts/src/calibration-v1";
const root = resolve(import.meta.dir, "../../contracts/v1/fixtures");
const fixture = (name: string): any => JSON.parse(readFileSync(resolve(root, `${name}.json`), "utf8"));
describe("K1 cross-language digital contracts", () => {
  test("command, ack and calibration valid parses", () => {
    expect(parseCommand(fixture("command.valid"))).toEqual(fixture("command.valid"));
    expect(parseCommandAck(fixture("command-ack.valid"))).toEqual(fixture("command-ack.valid"));
    expect(parseCalibration(fixture("calibration-record.valid"))).toEqual(fixture("calibration-record.valid"));
  });
  for (const row of fixture("command-negative-cases").parse) test(`negative command ${row.name}`, () => {
    expect(() => parseCommand({ ...fixture("command.valid"), ...row.patch })).toThrow();
  });
  for (const wire of ['{"x":1,"x":2}', '{"a":{"x":1,"x":2}}', '{"x":NaN}', '{"x":1.5}', '{"x":"\\ud800"}', '[]', '{} trailing']) test(`strict wire ${wire}`, () => expect(() => decodeWire(wire)).toThrow());
  test("byte-exact existing signing domain, real Ed25519 verification", () => {
    const golden = fixture("command-signing-golden");
    const key = createPublicKey({ key: Buffer.concat([Buffer.from("302a300506032b6570032100", "hex"), Buffer.from(golden.public_key_hex, "hex")]), format: "der", type: "spki" });
    for (const [prefix, name] of [["command", "command.valid"], ["calibration", "calibration-record.valid"]]) {
      const row = fixture(name); const bytes = payloadBytes(row);
      expect(Buffer.from(bytes).toString("hex")).toBe(golden[`${prefix}_signing_hex`]);
      expect(verify(null, bytes, key, Buffer.from(row.signature.value, "base64"))).toBe(true);
    }
    expect(canonicalJson({ z: 1, a: "é😀" })).toBe('{"a":"\\u00e9\\ud83d\\ude00\\u007f","z":1}');
  });
  for (const patch of [{ value: 1.2 }, { value: "-0" }, { value: "1.20" }, { value: "1e3" }, { digital_only: false }, { unit: "[" }, { unit: "m///s" }, { unit: "invented" }, { uncertainty: { value: "-1", coverage_factor: "2" } }]) test(`calibration negative ${JSON.stringify(patch)}`, () => expect(() => parseCalibration({ ...fixture("calibration-record.valid"), ...patch })).toThrow());
  test("retained ack, emit and integer counters reject", () => {
    expect(() => parseCommandAck(fixture("command-ack.valid"), true)).toThrow();
    expect(() => parseCommandAck({ ...fixture("command-ack.valid"), state_after: "emit" })).toThrow();
    expect(() => parseCommandAck({ ...fixture("command-ack.valid"), sequence_seen: 2 })).toThrow();
  });
  test("all shipped digital config fixtures migrate with unknown-version refusal", () => {
    for (const name of ["digital-config.v1", "digital-config.v2"]) {
      const row = fixture(name); const before = structuredClone(row);
      expect(migrateConfig(row)).toEqual(fixture("digital-config.v2")); expect(row).toEqual(before);
    }
    expect(() => migrateConfig({ schema_version: "poseidon.digital-config.v99" })).toThrow();
  });
});
