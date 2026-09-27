import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { IdentityPanel } from "../components/IdentityPanel";
import { DevicePanel } from "../components/DevicePanel";
import { AcquisitionPanel } from "../components/AcquisitionPanel";
import { AuditPanel } from "../components/AuditPanel";
import { ObservationPanel } from "../components/ObservationPanel";
import { LifecyclePanel } from "../components/LifecyclePanel";
import { ImportPanel } from "../components/ImportPanel";
import { EvidenceInspector } from "../components/EvidenceInspector";
import type { Identity } from "./platform";
import type { Recording } from "./api-types";

const viewer: Identity = { subject: "synthetic-viewer", role: "viewer", site_ids: ["synthetic-site"], device_id: null, auth_mode: "scoped_token" };
const recording: Recording = { schema_version: 1, recording_id: "synthetic-zero-candidates", site_id: "synthetic-site", zone_id: "synthetic-zone", device_id: "synthetic-device", started_at: "2026-09-08T00:00:00Z", provenance: "synthetic", wav_sha256: "0".repeat(64), calibration_status: "uncalibrated", duration_s: 1, sample_rate_hz: 8000, channel_count: 1, event_count: 0, reviewed_count: 0, imported_at: "2026-09-08T00:00:00Z", video: null };

describe("platform UI render boundaries", () => {
  test("viewer sees exact identity but cannot issue tokens", () => {
    const html = renderToStaticMarkup(<IdentityPanel identity={viewer} />);
    expect(html).toContain("synthetic-viewer");
    expect(html).toContain("scoped_token");
    expect(html).toContain("fieldset disabled");
    expect(html).not.toContain("One-time secret");
  });
  test("registry starts without fabricated device rows or readings", () => {
    const html = renderToStaticMarkup(<DevicePanel identity={viewer} />);
    expect(html).toContain("Registered identities, not a connected fleet");
    expect(html).toContain("fieldset disabled");
    expect(html).not.toContain("Connected devices");
    expect(html).not.toContain("21.5");
  });
  test("zero-candidate recording still renders independent observation workflow", () => {
    const html = renderToStaticMarkup(<ObservationPanel recording={recording} identity={viewer} onDirtyChange={() => {}} />);
    expect(html).toContain("Independent observation intervals");
    expect(html).toContain(recording.wav_sha256);
    expect(html).toContain("synthetic-viewer");
    expect(html).toContain("cannot save");
    expect(html).toContain("disabled");
  });
  test("acquisition, audit and lifecycle keep role and simulation boundaries", () => {
    expect(renderToStaticMarkup(<AcquisitionPanel identity={viewer} recording={recording} />)).toContain("fieldset disabled");
    expect(renderToStaticMarkup(<AuditPanel identity={viewer} />)).toContain("cannot read the admin audit trail");
    const html = renderToStaticMarkup(<LifecyclePanel identity={viewer} />);
    expect(html).toContain("Local simulated targets only");
    expect(html).toContain("fieldset disabled");
    expect(html).not.toContain('name="private_key"');
  });
  test("legacy import and candidate inspector remain mounted interfaces", () => {
    const html = renderToStaticMarkup(<ImportPanel empty={true} allowed={false} onSubmitted={() => {}} />);
    expect(html).toContain("Load synthetic demo");
    expect(html).toContain("disabled");
    expect(renderToStaticMarkup(<EvidenceInspector detail={null} waveform={null} loading={false} waveformLoading={false} error={null} onRetry={() => {}} onDirtyChange={() => {}} onReviewSaved={() => {}} onVideoAttached={() => {}} canWrite={false} />)).toContain("Inspect one candidate");
  });
});
