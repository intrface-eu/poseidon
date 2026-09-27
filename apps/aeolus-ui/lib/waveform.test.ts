import { describe, expect, test } from "bun:test";
import { amplitudeY, envelopePath, intervalRect } from "./waveform";

const box = { left: 40, top: 10, width: 900, height: 200 };

describe("waveform geometry", () => {
  test("maps full-scale amplitude to one normalized axis", () => {
    expect(amplitudeY(1, box)).toBe(10);
    expect(amplitudeY(0, box)).toBe(110);
    expect(amplitudeY(-1, box)).toBe(210);
  });

  test("builds a finite all-channel envelope path", () => {
    const path = envelopePath(
      [
        { start_s: 0, end_s: 0.5, min: -0.4, max: 0.7 },
        { start_s: 0.5, end_s: 1, min: -0.8, max: 0.2 },
      ],
      1,
      box,
    );
    expect(path.startsWith("M")).toBe(true);
    expect(path.endsWith("Z")).toBe(true);
    expect(path).not.toContain("NaN");
  });

  test("keeps a one-bucket recording valid", () => {
    const path = envelopePath([{ start_s: 0, end_s: 0.001, min: -0.2, max: 0.3 }], 0.001, box);
    expect(path).not.toContain("L L");
    expect(path).toMatch(/^M.+ L.+ Z$/);
  });

  test("clamps event intervals to the recording", () => {
    expect(intervalRect(-1, 2, 1, box)).toEqual({ x: 40, width: 900 });
  });
});
