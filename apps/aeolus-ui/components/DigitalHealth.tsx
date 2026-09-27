"use client";

import { useState, type FormEvent } from "react";
import type { ApiPage } from "@/lib/api-types";
import { apiRequest, jsonRequest } from "@/lib/client-api";
import { canAdmin, PLATFORM_API, type Device, type Identity } from "@/lib/platform";
import { canOperate, type Alarm, type DeviceHealth, type HealthProfile } from "@/lib/digital";
import { Ledger, PageControls, RequestError, errorMessage } from "./PlatformCommon";
import { useDigitalResource as useResource } from "@/lib/use-digital-resource";

export function DeviceHealthList({ version }: { version: number }) {
  const [offset, setOffset] = useState(0);
  const health = useResource<ApiPage<DeviceHealth>>(`${PLATFORM_API}/device-health?limit=25&offset=${offset}`, version);
  return <section className="platform-panel" aria-labelledby="device-health-title">
    <header className="platform-heading"><div><h2 id="device-health-title">Device receipt health</h2><p>API-derived telemetry age against each explicit profile. Online means a recent receipt, not hardware connectivity or safety.</p></div></header>
    <div className="inspection-block"><RequestError message={health.error} retry={health.reload} />
      {health.loading ? <p role="status">Refreshing receipt health…</p> : null}
      {health.data?.items.length === 0 ? <p className="list-empty">No registered identities in this scope. No health readings are assumed.</p> : null}
      {health.data ? <div className="table-scroll" tabIndex={0} aria-label="Device receipt health table"><table className="platform-table"><caption>Receipt age and explicit health thresholds</caption><thead><tr><th scope="col">Device / scope</th><th scope="col">Receipt health</th><th scope="col">Age (seconds)</th><th scope="col">Last telemetry (UTC)</th><th scope="col">Profile thresholds (seconds)</th></tr></thead><tbody>{health.data.items.map((row) => <tr key={row.device_id} data-device-health={row.device_id}><th scope="row"><span className="full-identifier">{row.device_id}</span><br /><span className="full-identifier">{row.site_id} / {row.zone_id ?? "No explicit zone"}</span></th><td><span className="tag neutral">{row.health}</span></td><td>{row.age_s ?? "No receipt"}</td><td className="full-identifier">{row.last_telemetry_at ?? "No telemetry"}</td><td>{row.profile ? `Stale ≥ ${row.profile.stale_after_s}; offline ≥ ${row.profile.offline_after_s}` : "Unprofiled; no inferred zone or commands"}</td></tr>)}</tbody></table></div> : null}
      <PageControls page={health.data} onPage={setOffset} loading={health.loading} />
    </div>
  </section>;
}

export function HealthProfileForm({ device, identity }: { device: Device; identity: Identity }) {
  const [zone, setZone] = useState("");
  const [stale, setStale] = useState("30");
  const [offline, setOffline] = useState("120");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<HealthProfile | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!canAdmin(identity)) return;
    setPending(true); setError(null);
    try {
      const profile = await apiRequest<HealthProfile>(`${PLATFORM_API}/devices/${encodeURIComponent(device.id)}/health-profile`, jsonRequest("PUT", { schema_version: "poseidon.device-health-profile.v1", zone_id: zone, stale_after_s: Number(stale), offline_after_s: Number(offline) }));
      setSaved(profile);
    } catch (caught) { setError(errorMessage(caught)); } finally { setPending(false); }
  }
  return <details><summary>Explicit zone and receipt-health profile</summary><p className="platform-note">Admin only. Profiles are immutable after enrollment. Missing legacy profiles remain unprofiled; the UI never copies a zone from a recording.</p>
    <form className="platform-form" onSubmit={submit}><fieldset disabled={!canAdmin(identity) || pending || Boolean(device.revoked_at)}>
      <label>Explicit device zone ID<input required maxLength={128} value={zone} onChange={(event) => setZone(event.target.value)} /></label>
      <label>Stale after seconds<input required type="number" min={1} max={86399} step={1} value={stale} onChange={(event) => setStale(event.target.value)} /></label>
      <label>Offline after seconds<input required type="number" min={2} max={86400} step={1} value={offline} onChange={(event) => setOffline(event.target.value)} /></label>
    </fieldset><button type="submit" className="button secondary" disabled={!canAdmin(identity) || pending || Boolean(device.revoked_at)}>{pending ? "Enrolling profile…" : "Enroll explicit health profile"}</button></form>
    <RequestError message={error} />{saved ? <div role="status"><p>Explicit profile enrolled. This does not establish a physical connection.</p><Ledger rows={[["Zone", saved.zone_id], ["Stale after (s)", saved.stale_after_s], ["Offline after (s)", saved.offline_after_s]]} /></div> : null}
  </details>;
}

export function AlarmList({ identity, version, onChanged }: { identity: Identity; version: number; onChanged: () => void }) {
  const [offset, setOffset] = useState(0);
  const alarms = useResource<ApiPage<Alarm>>(`${PLATFORM_API}/alarms?limit=25&offset=${offset}`, version);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  async function acknowledge(id: string) {
    setPending(id); setError(null); setMessage(null);
    try {
      const alarm = await apiRequest<Alarm>(`${PLATFORM_API}/alarms/${encodeURIComponent(id)}/acknowledge`, { method: "POST" });
      setMessage(`Acknowledged ${alarm.id} by ${alarm.acknowledged_by}. Acknowledgement does not clear the alarm or fault.`);
      onChanged();
    } catch (caught) { setError(errorMessage(caught)); } finally { setPending(null); }
  }
  return <section className="platform-panel" aria-labelledby="alarms-title"><header className="platform-heading"><div><h2 id="alarms-title">Local digital alarms</h2><p>Acknowledge the record, not a physical safety condition. Fault recovery is a separate signed command.</p></div></header><div className="inspection-block">
    <RequestError message={alarms.error} retry={alarms.reload} /><RequestError message={error} />{message ? <p role="status">{message}</p> : null}
    {alarms.loading ? <p role="status">Refreshing digital alarms…</p> : null}{alarms.data?.items.length === 0 ? <p className="list-empty">No alarm records in this scope. This is not a safety certification.</p> : null}
    {alarms.data?.items.map((alarm) => <details className="data-table-disclosure" key={alarm.id} data-alarm-id={alarm.id}><summary>{alarm.severity} · {alarm.source} · {alarm.cleared_at ? "cleared" : "open"} · {alarm.acknowledged_by ? "acknowledged" : "unacknowledged"} · {alarm.reason}</summary><div className="inspection-block"><Ledger rows={[["Alarm ID", alarm.id], ["Device", alarm.device_id], ["Site", alarm.site_id], ["Reason", alarm.reason], ["Opened (UTC)", alarm.opened_at], ["Cleared (UTC)", alarm.cleared_at ?? "Not cleared"], ["Acknowledged by", alarm.acknowledged_by ?? "Not acknowledged"], ["Acknowledged (UTC)", alarm.acknowledged_at ?? "Not acknowledged"]]} /><button type="button" className="button secondary" disabled={(!canOperate(identity) && !canAdmin(identity)) || Boolean(alarm.acknowledged_by) || Boolean(pending)} onClick={() => void acknowledge(alarm.id)}>{pending === alarm.id ? "Acknowledging…" : "Acknowledge alarm"}</button></div></details>)}
    <PageControls page={alarms.data} onPage={setOffset} loading={alarms.loading} />
  </div></section>;
}
