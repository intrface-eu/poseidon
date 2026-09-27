"use client";

import { useState, type FormEvent } from "react";
import type { ApiPage } from "@/lib/api-types";
import { apiRequest, jsonRequest } from "@/lib/client-api";
import { canAdmin, PLATFORM_API, type Device, type DeviceInput, type Identity, type Telemetry } from "@/lib/platform";
import { Ledger, PageControls, RequestError, SourceClock, errorMessage, useResource } from "./PlatformCommon";
import { AquilonMappingPanel } from "./AquilonMappingPanel";
import { HealthProfileForm } from "./DigitalHealth";

export function DevicePanel({ identity }: { identity: Identity }) {
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const devices = useResource<ApiPage<Device>>(`${PLATFORM_API}/devices?limit=25&offset=${offset}`, version);
  const [selected, setSelected] = useState(identity.device_id ?? "");
  const device = useResource<Device>(selected ? `${PLATFORM_API}/devices/${encodeURIComponent(selected)}` : null, version);
  const [draft, setDraft] = useState<DeviceInput>({ id: "", site_id: identity.site_ids[0] ?? "", label: "", kind: "reef", hardware_revision: "", source_kind: "synthetic" });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const admin = canAdmin(identity);
  async function create(event: FormEvent) {
    event.preventDefault(); if (!admin || !["synthetic", "bench"].includes(draft.source_kind)) return;
    setPending(true); setError(null); setMessage(null);
    try {
      const row = await apiRequest<Device>(`${PLATFORM_API}/devices`, jsonRequest("POST", draft));
      setSelected(row.id); setVersion((value) => value + 1); setMessage(`Registered ${row.id}. Registration does not establish a connection.`);
      setDraft((current) => ({ ...current, id: "", label: "", hardware_revision: "" }));
    } catch (caught) { setError(errorMessage(caught)); } finally { setPending(false); }
  }
  async function revoke() {
    if (!device.data || !admin || !window.confirm(`Revoke ${device.data.id}? Its telemetry ingestion and device credentials will stop working.`)) return;
    setPending(true); setError(null); setMessage(null);
    try { await apiRequest(`${PLATFORM_API}/devices/${encodeURIComponent(device.data.id)}/revoke`, { method: "POST" }); setVersion((value) => value + 1); setMessage("Device revoked. This changed local authorization, not physical hardware."); }
    catch (caught) { setError(errorMessage(caught)); } finally { setPending(false); }
  }
  return <div className="platform-stack">
    <section className="platform-panel" aria-labelledby="devices-title"><header className="platform-heading"><div><h2 id="devices-title">Device registry</h2><p>Registered identities, not a connected fleet. No live enrollment or hardware command is available.</p></div><button className="button secondary" type="button" onClick={() => setVersion((value) => value + 1)}>Refresh registry</button></header>
      <div className="platform-split"><div className="inspection-block"><RequestError message={devices.error} retry={() => setVersion((value) => value + 1)} />{devices.loading ? <p role="status">Loading registered identities…</p> : null}{devices.data?.items.length === 0 ? <p className="list-empty">No registered devices. Nothing is connected by default.</p> : null}{devices.data?.items.map((row) => <button type="button" key={row.id} className={`recording-row ${selected === row.id ? "selected" : ""}`} onClick={() => setSelected(row.id)}><strong>{row.label}</strong><span className="full-identifier">{row.id} · site {row.site_id}</span><span className="tag-row"><span className={`tag ${row.source_kind}`}>{row.source_kind}</span><span className="tag neutral">{row.revoked_at ? "Revoked" : "Registered · connection unknown"}</span></span></button>)}<PageControls page={devices.data} onPage={setOffset} /></div>
      <div className="inspection-block"><h3>Selected device</h3><RequestError message={device.error} retry={() => setVersion((value) => value + 1)} />{device.loading ? <p role="status">Loading device…</p> : null}{device.data ? <><Ledger rows={[["Device ID", device.data.id], ["Site", device.data.site_id], ["Label", device.data.label], ["Kind", device.data.kind], ["Hardware revision", device.data.hardware_revision], ["Source", device.data.source_kind], ["Registered", device.data.created_at], ["Revoked", device.data.revoked_at ?? "Not revoked"]]} /><button type="button" className="button secondary" disabled={!admin || pending || Boolean(device.data.revoked_at)} onClick={() => void revoke()}>Revoke device and its credentials</button><HealthProfileForm key={`health-${device.data.id}`} device={device.data} identity={identity} /><AquilonMappingPanel key={device.data.id} device={device.data} identity={identity} /></> : !selected ? <p className="platform-note">Select a registered identity to inspect exact provenance and its revocation state.</p> : null}</div></div>
      <div className="inspection-block"><details><summary>Register a synthetic or bench device</summary><p className="platform-note">Admin only. This creates a local registry record, not real field enrollment. Provision a scoped device token separately under Identity & access.</p><form className="platform-form" onSubmit={create}><fieldset disabled={!admin || pending}><label>Device ID<input required maxLength={128} pattern="[A-Za-z0-9][A-Za-z0-9._-]*" value={draft.id} onChange={(event) => setDraft((value) => ({ ...value, id: event.target.value }))} /></label><label>Device site ID<input required maxLength={128} value={draft.site_id} onChange={(event) => setDraft((value) => ({ ...value, site_id: event.target.value }))} /></label><label>Device label<input required maxLength={160} value={draft.label} onChange={(event) => setDraft((value) => ({ ...value, label: event.target.value }))} /></label><label>Device kind<select value={draft.kind} onChange={(event) => setDraft((value) => ({ ...value, kind: event.target.value as DeviceInput["kind"] }))}><option value="reef">REEF</option><option value="aquilon">AQUILON</option><option value="hub">Hub</option></select></label><label>Hardware revision<input required maxLength={80} value={draft.hardware_revision} onChange={(event) => setDraft((value) => ({ ...value, hardware_revision: event.target.value }))} /></label><label>Device source<select value={draft.source_kind} onChange={(event) => setDraft((value) => ({ ...value, source_kind: event.target.value as "synthetic" | "bench" }))}><option value="synthetic">Synthetic · software only</option><option value="bench">Bench · not field deployment</option></select></label></fieldset><button type="submit" className="button primary" disabled={!admin || pending}>{pending ? "Registering…" : "Register local test device"}</button></form></details><RequestError message={error} />{message ? <p role="status">{message}</p> : null}</div>
    </section>
    <TelemetryPanel identity={identity} deviceId={selected} key={selected} />
  </div>;
}

function TelemetryPanel({ identity, deviceId }: { identity: Identity; deviceId: string }) {
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [site, setSite] = useState("");
  const [filterSite, setFilterSite] = useState("");
  const query = new URLSearchParams({ limit: "25", offset: String(offset) });
  if (deviceId) query.set("device_id", deviceId);
  if (filterSite) query.set("site_id", filterSite);
  const telemetry = useResource<ApiPage<Telemetry>>(`${PLATFORM_API}/telemetry?${query}`, version);
  return <section className="platform-panel" aria-labelledby="telemetry-title"><header className="platform-heading"><div><h2 id="telemetry-title">Telemetry receipts</h2><p>Exact stored values with units, source and clock quality. No inferred live status, no generated readings.</p></div><button className="button secondary" type="button" onClick={() => setVersion((value) => value + 1)}>Refresh telemetry</button></header><div className="inspection-block"><form className="platform-filter" onSubmit={(event) => { event.preventDefault(); setFilterSite(site.trim()); setOffset(0); }}><label>Filter telemetry by site<input value={site} onChange={(event) => setSite(event.target.value)} maxLength={128} /></label><button type="submit" className="button secondary">Apply site filter</button><span>{deviceId ? `Device: ${deviceId}` : "All authorized devices"}</span></form><RequestError message={telemetry.error} retry={() => setVersion((value) => value + 1)} />{telemetry.loading ? <p role="status">Loading telemetry receipts…</p> : null}{telemetry.data?.items.length === 0 ? <p className="list-empty">No telemetry receipts in this scope. Registration alone produces no measurements.</p> : null}{telemetry.data?.items.map((row) => <details key={row.id} className="data-table-disclosure"><summary>{row.envelope.provenance.source_kind} · {row.envelope.device_id} · sequence {row.envelope.sequence} · received {row.received_at}</summary><div className="inspection-block"><Ledger rows={[["Receipt ID", row.id], ["Device", row.envelope.device_id], ["Site", row.envelope.site_id], ["Boot ID", row.envelope.boot_id], ["Sequence", row.envelope.sequence], ["Observed", row.envelope.observed_at ?? "Unknown; no inferred event time"], ["Received", row.received_at], ["Actor", row.actor_subject], ["Delivery age (s)", row.envelope.delivery_age_s]]} /><p className="platform-note">Delivery age is a sender claim, not attested age. Digital RMS is normalized PCM16 full-scale, not underwater SPL.</p><SourceClock provenance={row.envelope.provenance} clock={row.envelope.clock_quality} />{row.envelope.radio ? <><h3>Radio provenance and unverified claims</h3><Ledger rows={[["DevEUI", row.envelope.radio.dev_eui], ["Uptime (s)", row.envelope.radio.uptime_s], ["Power mode", row.envelope.radio.power_mode], ["Clock claim", row.envelope.radio.clock_claim], ["Claimed Unix time (s)", row.envelope.radio.observed_at_unix_s], ["Network received", row.envelope.radio.network_received_at], ["Frame SHA-256", row.envelope.radio.frame_sha256], ["Calibration code", row.envelope.radio.calibration_code]]} /><p className="platform-note">Radio time and calibration claims do not establish synchronized UTC or calibrated physical measurements.</p></> : null}<div className="table-scroll"><table className="platform-table"><caption>Measurements in receipt {row.id}</caption><thead><tr><th scope="col">Measurement</th><th scope="col">Value</th><th scope="col">Unit</th><th scope="col">Quality</th><th scope="col">Calibration ID</th></tr></thead><tbody>{row.envelope.measurements.map((measurement, index) => <tr key={index}><th scope="row">{measurement.name}</th><td>{measurement.value ?? "No valid value"}</td><td>{measurement.unit}</td><td>{measurement.quality}</td><td>{measurement.calibration_id ?? "None declared"}</td></tr>)}</tbody></table></div></div></details>)}<PageControls page={telemetry.data} onPage={setOffset} /></div>{identity.role === "device" ? <div className="inspection-block"><h3>Device credential scope</h3><p>This session can query its own receipts. Telemetry ingestion uses the authenticated adapter and the reviewed envelope contract; the operator UI does not manufacture measurements.</p></div> : null}</section>;
}
